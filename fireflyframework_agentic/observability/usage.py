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

from fireflyframework_agentic.config import get_config
from fireflyframework_agentic.observability.budget import BudgetGate, BudgetRule
from fireflyframework_agentic.observability.cost.resolvers import (
    CostContext,
    CostFn,
    resolve_cost,
)
from fireflyframework_agentic.observability.cost.tiers import CallTier
from fireflyframework_agentic.observability.sinks import (
    CostSink,
    EventBusSink,
    OTelMetricsSink,
    _emit_safely,
)

logger = logging.getLogger(__name__)


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
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                 "cost_usd": 0.0, "requests": 0}
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                 "cost_usd": 0.0, "requests": 0}
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
        tier: CallTier = CallTier.STANDARD,
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
            tier=tier,
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
        if self._resolver is None:
            return resolve_cost(ctx)
        if callable(self._resolver):
            result = self._resolver(ctx)
            return 0.0 if result is None else float(result)
        return resolve_cost(ctx, self._resolver)

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
    """Construct the module-level tracker with defaults driven by config."""
    sinks: list[CostSink] = [OTelMetricsSink(), EventBusSink()]
    gate: BudgetGate | None = None
    max_records = 10_000
    try:
        cfg = get_config()
        if cfg.budget_limit_usd is not None:
            gate = BudgetGate([BudgetRule(name="config_global", limit_usd=cfg.budget_limit_usd)])
        max_records = cfg.usage_tracker_max_records
    except Exception:  # noqa: BLE001
        logger.debug("Falling back to defaults for usage tracker", exc_info=True)
    return UsageTracker(sinks=sinks, gate=gate, max_records=max_records)


default_usage_tracker = _build_default_tracker()
