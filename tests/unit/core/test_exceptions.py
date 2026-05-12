import pytest

from fireflyframework_agentic.exceptions import BudgetExceededError, QuotaError


def test_budget_exceeded_error_legacy_construction() -> None:
    err = BudgetExceededError("budget blew up")
    assert str(err) == "budget blew up"
    assert isinstance(err, QuotaError)
    assert err.rule_name == ""
    assert err.spend_usd == 0.0
    assert err.limit_usd == 0.0


def test_budget_exceeded_error_structured_fields() -> None:
    err = BudgetExceededError(
        "rule 'acme' exceeded",
        rule_name="acme",
        spend_usd=12.5,
        limit_usd=10.0,
    )
    assert err.rule_name == "acme"
    assert err.spend_usd == 12.5
    assert err.limit_usd == 10.0
