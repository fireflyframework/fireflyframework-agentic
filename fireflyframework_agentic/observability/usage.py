# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Usage tracking for LLM API calls.

:class:`UsageTracker` is a thin orchestrator: it resolves cost via a
``CostResolver`` chain, builds a :class:`UsageRecord`, hands the record
to a :class:`BudgetGate` for accumulation/enforcement, then fans the
record out to a chain of :class:`CostSink` consumers.

The legacy ``record(usage)`` low-level entry is preserved for in-tree
producers that already construct a :class:`UsageRecord` (agents,
reasoning, experiments).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage

from fireflyframework_agentic.config import FireflyAgenticConfig, on_config_installed
from fireflyframework_agentic.observability.budget import BudgetGate, BudgetRule
from fireflyframework_agentic.observability.cost_resolvers import (
    CostContext,
    CostFn,
    resolve_cost,
)
from fireflyframework_agentic.observability.sinks import (
    CostSink,
    EventBusSink,
    OTelMetricsSink,
    _emit_safely,
)

logger = logging.getLogger(__name__)


def resolve_run_usage(result: Any) -> Any | None:
    """Return the ``RunUsage`` for a pydantic-ai result, or ``None``.

    pydantic-ai 1.x exposes ``result.usage`` as a *property* (calling it — the
    legacy ``result.usage()`` form — emits a ``PydanticAIDeprecationWarning``),
    while pre-1.x SDKs and some test doubles expose it as a method. If the
    attribute is already a ``RunUsage`` (the property form, including 1.x's
    deprecated-callable wrapper which subclasses it), use it directly without
    calling; if it is callable (the method form), call it once.
    """
    usage = getattr(result, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, RunUsage):
        return usage
    if callable(usage):
        return usage()
    return usage


def reasoning_tokens_not_in_output(usage: Any) -> int:
    """Reasoning tokens that the provider does **not** already fold into
    ``output_tokens`` (and that therefore must be priced separately).

    Today this is exactly Gemini's ``details["thoughts_tokens"]``: Gemini's
    ``output_tokens`` (``candidates_token_count``) excludes thinking. It is keyed
    on the Gemini-specific ``thoughts_tokens`` detail deliberately — OpenAI's
    ``details["reasoning_tokens"]`` is **already** counted in ``output_tokens``
    (reading it would double-count), and Anthropic folds thinking into
    ``output_tokens`` too. So every non-Gemini provider contributes ``0``.
    """
    details = getattr(usage, "details", None) or {}
    try:
        return int(details.get("thoughts_tokens", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


class UsageRecord(BaseModel):
    """A single LLM usage observation. Schema is intentionally stable."""

    agent: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    request_count: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""


class UsageSummary(BaseModel):
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_requests: int = 0
    total_latency_ms: float = 0.0
    record_count: int = 0
    by_agent: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_model: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _aggregate(records: list[UsageRecord]) -> UsageSummary:
    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "requests": 0}
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "requests": 0}
    )
    total_in = total_out = total_tok = total_req = 0
    total_cost = total_lat = 0.0
    for r in records:
        total_in += r.input_tokens
        total_out += r.output_tokens
        total_tok += r.total_tokens
        total_req += r.request_count
        total_cost += r.cost_usd
        total_lat += r.latency_ms
        if r.agent:
            a = by_agent[r.agent]
            a["input_tokens"] += r.input_tokens
            a["output_tokens"] += r.output_tokens
            a["total_tokens"] += r.total_tokens
            a["cost_usd"] += r.cost_usd
            a["requests"] += r.request_count
        if r.model:
            m = by_model[r.model]
            m["input_tokens"] += r.input_tokens
            m["output_tokens"] += r.output_tokens
            m["total_tokens"] += r.total_tokens
            m["cost_usd"] += r.cost_usd
            m["requests"] += r.request_count
    return UsageSummary(
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_tokens=total_tok,
        total_cost_usd=total_cost,
        total_requests=total_req,
        total_latency_ms=total_lat,
        record_count=len(records),
        by_agent=dict(by_agent),
        by_model=dict(by_model),
    )


# Type alias: a resolver is either the full chain (Sequence[CostFn]) or a single callable.
_ResolverArg = Sequence[CostFn] | Callable[[CostContext], float] | None


class UsageTracker:
    """Thread-safe accumulator + fan-out for :class:`UsageRecord`."""

    def __init__(
        self,
        *,
        sinks: Sequence[CostSink] | None = None,
        resolver: _ResolverArg = None,
        gate: BudgetGate | None = None,
        max_records: int = 0,
    ) -> None:
        self._records: list[UsageRecord] = []
        self._cumulative_cost: float = 0.0
        self._max_records = max_records
        self._lock = threading.Lock()
        self._sinks: list[CostSink] = list(sinks or [])
        self._resolver = resolver
        self._gate = gate

    # -- High-level entry ------------------------------------------------
    def record_call(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        reasoning_tokens: int = 0,
        provider_payload: Mapping[str, Any] | None = None,
        agent: str = "",
        correlation_id: str = "",
        latency_ms: float = 0.0,
        request_count: int = 0,
        scope_ctx=None,
    ) -> UsageRecord:
        ctx = CostContext(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            reasoning_tokens=reasoning_tokens,
            provider_payload=provider_payload,
        )
        cost = self._resolve(ctx)
        record = UsageRecord(
            agent=agent,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens + reasoning_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            request_count=request_count,
            cost_usd=cost,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
        )
        self.record(record, scope_ctx=scope_ctx)
        return record

    def _resolve(self, ctx: CostContext) -> float:
        # resolve_cost returns float | None (strict mode raises instead);
        # UsageRecord.cost_usd is a float, so coerce None to 0.0 here.
        # The cost_unknown metric and WARNING have already fired upstream.
        if self._resolver is None:
            result = resolve_cost(ctx)
        elif callable(self._resolver):
            result = self._resolver(ctx)
        else:
            result = resolve_cost(ctx, self._resolver)
        return 0.0 if result is None else float(result)

    # -- Low-level entry -------------------------------------------------
    def record(self, usage: UsageRecord, scope_ctx=None) -> None:
        with self._lock:
            self._records.append(usage)
            self._cumulative_cost += usage.cost_usd
            if self._max_records > 0 and len(self._records) > self._max_records:
                excess = len(self._records) - self._max_records
                del self._records[:excess]
        if self._gate is not None:
            self._gate.commit(usage, scope_ctx)
        for sink in self._sinks:
            _emit_safely(sink, usage)

    # -- Sink management -------------------------------------------------
    #: The name of the budget rule a configuration's ``budget_limit_usd`` becomes. One rule,
    #: replaced on every install, so two configs never stack two global limits.
    CONFIG_RULE = "config_global"

    @property
    def max_records(self) -> int:
        """How many records are kept (``0`` keeps every one)."""
        return self._max_records

    def apply_config(self, config: FireflyAgenticConfig) -> None:
        """Take ``usage_tracker_max_records`` and ``budget_limit_usd`` from *config*, in place.

        In place, because the process tracker is one object with many holders: ``agents.base``
        imported it, the docs read ``default_usage_tracker.get_summary()``, tests patch it by
        its module path. Rebuilding it on ``set_config`` would leave every holder with the old
        one. The record cap is applied immediately (a smaller cap trims the oldest records);
        the config rule of the budget gate is replaced, other rules on the gate are kept, and
        their accumulated spend is not reset.
        """
        with self._lock:
            self._max_records = config.usage_tracker_max_records
            if self._max_records > 0 and len(self._records) > self._max_records:
                del self._records[: len(self._records) - self._max_records]
        others = [r for r in (self._gate.rules if self._gate is not None else ()) if r.name != self.CONFIG_RULE]
        if config.budget_limit_usd is not None:
            others.append(BudgetRule(name=self.CONFIG_RULE, limit_usd=config.budget_limit_usd))
        if others:
            self._gate = BudgetGate(others) if self._gate is None else self._gate.with_rules(others)
        else:
            self._gate = None

    @classmethod
    def for_config(
        cls,
        config: FireflyAgenticConfig,
        *,
        sinks: Sequence[CostSink] | None = None,
        resolver: _ResolverArg = None,
    ) -> UsageTracker:
        """A tracker sized and gated by *config* — the ledger an agent or a tenant owns.

        ``FireflyAgent(config=cfg)`` governs the agent, not the process ledger; a host that
        wants the agent's ``usage_tracker_max_records`` / ``budget_limit_usd`` to bound a
        ledger of that agent's own builds one here and passes it as ``usage_tracker=``.
        """
        tracker = cls(sinks=sinks, resolver=resolver)
        tracker.apply_config(config)
        return tracker

    def add_sink(self, sink: CostSink) -> None:
        self._sinks.append(sink)

    # -- Read accessors --------------------------------------------------
    @property
    def records(self) -> list[UsageRecord]:
        with self._lock:
            return list(self._records)

    @property
    def cumulative_cost_usd(self) -> float:
        with self._lock:
            return self._cumulative_cost

    def get_summary(self) -> UsageSummary:
        with self._lock:
            return _aggregate(list(self._records))

    def get_summary_for_agent(self, agent_name: str) -> UsageSummary:
        with self._lock:
            filtered = [r for r in self._records if r.agent == agent_name]
        return _aggregate(filtered)

    def get_summary_for_correlation(self, correlation_id: str) -> UsageSummary:
        with self._lock:
            filtered = [r for r in self._records if r.correlation_id == correlation_id]
        return _aggregate(filtered)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._cumulative_cost = 0.0


def _build_default_tracker() -> UsageTracker:
    """Construct the module-level tracker and keep it in step with the installed config.

    The tracker is built at import time, and ``agents.base`` imports this module, so every
    host has it before it calls ``set_config``. It therefore subscribes to the install
    (:func:`~fireflyframework_agentic.config.on_config_installed`), which also runs once now
    with the current config; a config that cannot be read at import (a bad environment
    variable) leaves the defaults in place rather than failing the import.
    """
    tracker = UsageTracker(sinks=[OTelMetricsSink(), EventBusSink()], max_records=10_000)
    try:
        on_config_installed(tracker.apply_config)
    except Exception:  # noqa: BLE001
        logger.debug("Falling back to defaults for usage tracker", exc_info=True)
    return tracker


default_usage_tracker = _build_default_tracker()
