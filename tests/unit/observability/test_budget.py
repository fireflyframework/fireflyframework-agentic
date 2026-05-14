from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
    _rule_matches,
)
from fireflyframework_agentic.observability.usage import UsageRecord


def test_budget_mode_values() -> None:
    assert BudgetMode.HARD == "hard"
    assert BudgetMode.SOFT == "soft"


def test_budget_window_values() -> None:
    assert {BudgetWindow.LIFETIME, BudgetWindow.MONTHLY, BudgetWindow.DAILY} == {
        "lifetime",
        "monthly",
        "daily",
    }


def test_scope_context_to_match_dict_builtin_keys() -> None:
    ctx = ScopeContext(tenant="acme", agent="writer", model="openai:gpt-4o", correlation_id="run-1")
    d = ctx.to_match_dict()
    assert d == {"tenant": "acme", "agent": "writer", "model": "openai:gpt-4o", "correlation_id": "run-1"}


def test_scope_context_to_match_dict_merges_labels() -> None:
    ctx = ScopeContext(tenant="acme", labels={"env": "prod", "feature": "summary"})
    d = ctx.to_match_dict()
    assert d == {"tenant": "acme", "env": "prod", "feature": "summary"}


def test_scope_context_builtin_wins_over_labels() -> None:
    ctx = ScopeContext(tenant="real", labels={"tenant": "fake"})
    assert ctx.to_match_dict()["tenant"] == "real"


def test_scope_context_omits_empty_builtins() -> None:
    ctx = ScopeContext(tenant="", agent="writer")
    assert ctx.to_match_dict() == {"agent": "writer"}


def test_rule_matches_empty_match_matches_everything() -> None:
    rule = BudgetRule(name="global", limit_usd=10.0, match={})
    assert _rule_matches(rule, ScopeContext(tenant="acme"))


def test_rule_matches_single_key() -> None:
    rule = BudgetRule(name="acme-only", limit_usd=10.0, match={"tenant": "acme"})
    assert _rule_matches(rule, ScopeContext(tenant="acme"))
    assert not _rule_matches(rule, ScopeContext(tenant="other"))


def test_rule_matches_is_and_of_keys() -> None:
    rule = BudgetRule(name="prod-writer", limit_usd=10.0, match={"agent": "writer", "env": "prod"})
    assert _rule_matches(rule, ScopeContext(agent="writer", labels={"env": "prod"}))
    assert not _rule_matches(rule, ScopeContext(agent="writer", labels={"env": "dev"}))
    assert not _rule_matches(rule, ScopeContext(agent="reader", labels={"env": "prod"}))


def test_budget_rule_defaults() -> None:
    rule = BudgetRule(name="x", limit_usd=5.0)
    assert rule.mode == BudgetMode.HARD
    assert rule.window == BudgetWindow.LIFETIME
    assert rule.match == {}


def test_gate_commit_accumulates_and_raises_on_hard() -> None:
    gate = BudgetGate([BudgetRule(name="global", limit_usd=1.0)])
    ctx = ScopeContext()
    gate.commit(UsageRecord(cost_usd=0.4), ctx)
    gate.commit(UsageRecord(cost_usd=0.5), ctx)
    assert gate.spend("global") == pytest.approx(0.9)
    with pytest.raises(BudgetExceededError) as exc:
        gate.commit(UsageRecord(cost_usd=0.2), ctx)
    assert exc.value.rule_name == "global"
    assert exc.value.limit_usd == 1.0


def test_gate_commit_soft_logs_no_raise(caplog: pytest.LogCaptureFixture) -> None:
    gate = BudgetGate([BudgetRule(name="g", limit_usd=1.0, mode=BudgetMode.SOFT)])
    with caplog.at_level("WARNING"):
        gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())
    assert any("budget" in r.message.lower() for r in caplog.records)
    assert gate.spend("g") == pytest.approx(2.0)


def test_gate_precheck_blocks_hard_overrun() -> None:
    gate = BudgetGate([BudgetRule(name="g", limit_usd=1.0)])
    gate.commit(UsageRecord(cost_usd=0.95), ScopeContext())
    with pytest.raises(BudgetExceededError):
        gate.precheck(estimated_cost_usd=0.1, ctx=ScopeContext())


def test_gate_precheck_zero_estimate_is_noop() -> None:
    gate = BudgetGate([BudgetRule(name="g", limit_usd=1.0)])
    gate.commit(UsageRecord(cost_usd=0.95), ScopeContext())
    gate.precheck(estimated_cost_usd=0.0, ctx=ScopeContext())  # no raise


def test_gate_only_applies_matching_rules() -> None:
    gate = BudgetGate([BudgetRule(name="acme", limit_usd=1.0, match={"tenant": "acme"})])
    gate.commit(UsageRecord(cost_usd=2.0), ScopeContext(tenant="other"))  # not matched, no raise
    assert gate.spend("acme") == 0.0


def test_gate_reset_single_rule_and_all() -> None:
    gate = BudgetGate([BudgetRule(name="a", limit_usd=10.0), BudgetRule(name="b", limit_usd=10.0)])
    gate.commit(UsageRecord(cost_usd=1.0), ScopeContext())
    gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())
    gate.reset("a")
    assert gate.spend("a") == 0.0
    assert gate.spend("b") == pytest.approx(3.0)
    gate.reset()
    assert gate.spend("b") == 0.0


def test_gate_resets_accumulator_when_daily_bucket_changes() -> None:
    gate = BudgetGate([BudgetRule(name="d", limit_usd=10.0, window=BudgetWindow.DAILY)])

    day1 = datetime(2026, 5, 12, 23, 30, tzinfo=UTC)
    day2 = datetime(2026, 5, 13, 0, 30, tzinfo=UTC)

    with patch("fireflyframework_agentic.observability.budget.datetime") as dt:
        dt.now.return_value = day1
        gate.commit(UsageRecord(cost_usd=8.0), ScopeContext())
        assert gate.spend("d") == pytest.approx(8.0)

        dt.now.return_value = day2
        gate.commit(UsageRecord(cost_usd=3.0), ScopeContext())  # new bucket; no raise
        assert gate.spend("d") == pytest.approx(3.0)


def test_gate_resets_accumulator_when_monthly_bucket_changes() -> None:
    gate = BudgetGate([BudgetRule(name="m", limit_usd=10.0, window=BudgetWindow.MONTHLY)])
    mid_april = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    mid_may = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    with patch("fireflyframework_agentic.observability.budget.datetime") as dt:
        dt.now.return_value = mid_april
        gate.commit(UsageRecord(cost_usd=9.0), ScopeContext())
        dt.now.return_value = mid_may
        gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())  # new month bucket
        assert gate.spend("m") == pytest.approx(2.0)


def test_gate_lifetime_never_resets() -> None:
    gate = BudgetGate([BudgetRule(name="l", limit_usd=100.0, window=BudgetWindow.LIFETIME)])
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2027, 6, 30, tzinfo=UTC)
    with patch("fireflyframework_agentic.observability.budget.datetime") as dt:
        dt.now.return_value = t1
        gate.commit(UsageRecord(cost_usd=3.0), ScopeContext())
        dt.now.return_value = t2
        gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())
        assert gate.spend("l") == pytest.approx(5.0)
