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

from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability._windows import bucket_key

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
