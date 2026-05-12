from fireflyframework_agentic.observability.budget import (
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
    _rule_matches,
)


def test_budget_mode_values() -> None:
    assert BudgetMode.HARD == "hard"
    assert BudgetMode.SOFT == "soft"


def test_budget_window_values() -> None:
    assert {BudgetWindow.LIFETIME, BudgetWindow.MONTHLY, BudgetWindow.DAILY} == {
        "lifetime", "monthly", "daily",
    }


def test_scope_context_to_match_dict_builtin_keys() -> None:
    ctx = ScopeContext(tenant="acme", agent="writer", model="openai:gpt-4o",
                       correlation_id="run-1")
    d = ctx.to_match_dict()
    assert d == {"tenant": "acme", "agent": "writer", "model": "openai:gpt-4o",
                 "correlation_id": "run-1"}


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


def test_rule_matches_is_AND_of_keys() -> None:
    rule = BudgetRule(name="prod-writer", limit_usd=10.0,
                      match={"agent": "writer", "env": "prod"})
    assert _rule_matches(rule, ScopeContext(agent="writer", labels={"env": "prod"}))
    assert not _rule_matches(rule, ScopeContext(agent="writer", labels={"env": "dev"}))
    assert not _rule_matches(rule, ScopeContext(agent="reader", labels={"env": "prod"}))


def test_budget_rule_defaults() -> None:
    rule = BudgetRule(name="x", limit_usd=5.0)
    assert rule.mode == BudgetMode.HARD
    assert rule.window == BudgetWindow.LIFETIME
    assert rule.match == {}
