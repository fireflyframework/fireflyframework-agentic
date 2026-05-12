# fireflyframework_agentic/observability/budget.py
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Budget enforcement with scoped, windowed rules.

A :class:`BudgetGate` holds a sequence of :class:`BudgetRule` objects.
Each rule has a window (calendar-aligned), a mode (hard | soft), and a
``match`` dict that filters which calls it applies to.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability._windows import bucket_key

if TYPE_CHECKING:
    from fireflyframework_agentic.observability.usage import UsageRecord

logger = logging.getLogger(__name__)


class BudgetMode(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class BudgetWindow(StrEnum):
    LIFETIME = "lifetime"
    MONTHLY = "monthly"
    DAILY = "daily"


@dataclass(frozen=True)
class ScopeContext:
    """Identity / attribution dimensions for a single LLM call."""

    tenant: str = ""
    agent: str = ""
    model: str = ""
    correlation_id: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_match_dict(self) -> dict[str, str]:
        """Flatten to a string→string mapping for ``BudgetRule.match``.

        Built-in fields win on collision with labels; empty built-in
        fields are omitted (so a rule keyed on ``tenant`` does not match
        a call whose tenant is the empty string).
        """
        out: dict[str, str] = dict(self.labels)
        for key, value in (
            ("tenant", self.tenant),
            ("agent", self.agent),
            ("model", self.model),
            ("correlation_id", self.correlation_id),
        ):
            if value:
                out[key] = value
        return out


@dataclass(frozen=True)
class BudgetRule:
    name: str
    limit_usd: float
    mode: BudgetMode = BudgetMode.HARD
    window: BudgetWindow = BudgetWindow.LIFETIME
    match: Mapping[str, str] = field(default_factory=dict)


def _rule_matches(rule: BudgetRule, ctx: ScopeContext) -> bool:
    """Return True iff every (k, v) in rule.match is in ctx.to_match_dict()."""
    if not rule.match:
        return True
    flat = ctx.to_match_dict()
    return all(flat.get(k) == v for k, v in rule.match.items())


class BudgetGate:
    """Hold a set of :class:`BudgetRule` accumulators and enforce them."""

    def __init__(self, rules: Sequence[BudgetRule]) -> None:
        self._rules: tuple[BudgetRule, ...] = tuple(rules)
        # rule_name -> (bucket_key, accumulated_usd)
        self._state: dict[str, tuple[str, float]] = {r.name: ("", 0.0) for r in self._rules}
        self._lock = threading.Lock()

    def precheck(self, estimated_cost_usd: float, ctx: ScopeContext | None = None) -> None:
        """Raise on HARD breach if the estimated cost would push spend over the limit."""
        if estimated_cost_usd <= 0.0:
            return
        ctx = ctx or ScopeContext()
        now = datetime.now(UTC)
        with self._lock:
            for rule in self._rules:
                if not _rule_matches(rule, ctx):
                    continue
                bk = bucket_key(rule.window.value, now)
                stored_bk, accumulated = self._state[rule.name]
                if stored_bk != bk:
                    accumulated = 0.0
                projected = accumulated + estimated_cost_usd
                if projected > rule.limit_usd and rule.mode == BudgetMode.HARD:
                    raise BudgetExceededError(
                        f"Budget '{rule.name}' would be exceeded: ${projected:.4f} > ${rule.limit_usd:.4f}",
                        rule_name=rule.name,
                        spend_usd=projected,
                        limit_usd=rule.limit_usd,
                    )

    def commit(self, record: UsageRecord, ctx: ScopeContext | None = None) -> None:
        """Add ``record.cost_usd`` to every matching rule. Raise on HARD breach."""
        cost = record.cost_usd
        if cost <= 0.0:
            return
        ctx = ctx or ScopeContext()
        now = datetime.now(UTC)
        to_raise: BudgetExceededError | None = None
        with self._lock:
            for rule in self._rules:
                if not _rule_matches(rule, ctx):
                    continue
                bk = bucket_key(rule.window.value, now)
                stored_bk, accumulated = self._state[rule.name]
                if stored_bk != bk:
                    accumulated = 0.0
                accumulated += cost
                self._state[rule.name] = (bk, accumulated)
                if accumulated > rule.limit_usd:
                    msg = f"Budget '{rule.name}' exceeded: ${accumulated:.4f} > ${rule.limit_usd:.4f}"
                    if rule.mode == BudgetMode.HARD:
                        to_raise = BudgetExceededError(
                            msg,
                            rule_name=rule.name,
                            spend_usd=accumulated,
                            limit_usd=rule.limit_usd,
                        )
                    else:
                        logger.warning("%s (mode=soft)", msg)
        if to_raise is not None:
            raise to_raise

    def spend(self, rule_name: str) -> float:
        """Return accumulated spend for a rule in the current window bucket."""
        with self._lock:
            return self._state.get(rule_name, ("", 0.0))[1]

    def reset(self, rule_name: str | None = None) -> None:
        """Reset one rule's accumulator, or all if name is None."""
        with self._lock:
            if rule_name is None:
                for name in self._state:
                    self._state[name] = ("", 0.0)
            elif rule_name in self._state:
                self._state[rule_name] = ("", 0.0)
