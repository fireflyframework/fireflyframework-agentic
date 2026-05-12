from fireflyframework_agentic.observability.budget import (
    BudgetMode,
    BudgetWindow,
    ScopeContext,
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
