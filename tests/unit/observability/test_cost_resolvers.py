from fireflyframework_agentic.observability.cost.resolvers import CostContext
from fireflyframework_agentic.observability.cost.tiers import CallTier


def test_cost_context_defaults() -> None:
    ctx = CostContext(model="openai:gpt-4o", input_tokens=100, output_tokens=50)
    assert ctx.cache_creation_tokens == 0
    assert ctx.cache_read_tokens == 0
    assert ctx.reasoning_tokens == 0
    assert ctx.tier == CallTier.STANDARD
    assert ctx.provider_payload is None


def test_cost_context_is_frozen() -> None:
    import dataclasses

    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.model = "y"  # type: ignore[misc]


import pytest  # noqa: E402

from fireflyframework_agentic.observability.cost.resolvers import provider_reported_cost


def test_provider_reported_cost_openrouter() -> None:
    ctx = CostContext(
        model="openrouter:any/model",
        input_tokens=1, output_tokens=1,
        provider_payload={"usage": {"cost": 0.0123}},
    )
    assert provider_reported_cost(ctx) == 0.0123


def test_provider_reported_cost_absent_returns_none() -> None:
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1, provider_payload={})
    assert provider_reported_cost(ctx) is None


def test_provider_reported_cost_no_payload_returns_none() -> None:
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1, provider_payload=None)
    assert provider_reported_cost(ctx) is None


def test_provider_reported_cost_malformed_returns_none() -> None:
    ctx = CostContext(
        model="x", input_tokens=1, output_tokens=1,
        provider_payload={"usage": {"cost": "not-a-number"}},
    )
    assert provider_reported_cost(ctx) is None
