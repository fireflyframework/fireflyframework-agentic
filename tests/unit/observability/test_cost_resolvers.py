import dataclasses
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from fireflyframework_agentic.observability import cost_resolvers as _resolvers_mod
from fireflyframework_agentic.observability.cost_resolvers import (
    DEFAULT_RESOLVERS,
    CostContext,
    genai_prices_cost,
    provider_reported_cost,
    resolve_cost,
)


def test_cost_context_defaults() -> None:
    ctx = CostContext(model="openai:gpt-4o", input_tokens=100, output_tokens=50)
    assert ctx.cache_creation_tokens == 0
    assert ctx.cache_read_tokens == 0
    assert ctx.reasoning_tokens == 0
    assert ctx.provider_payload is None


def test_cost_context_is_frozen() -> None:
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.model = "y"  # type: ignore[misc]


def test_provider_reported_cost_openrouter() -> None:
    ctx = CostContext(
        model="openrouter:any/model",
        input_tokens=1,
        output_tokens=1,
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
        model="x",
        input_tokens=1,
        output_tokens=1,
        provider_payload={"usage": {"cost": "not-a-number"}},
    )
    assert provider_reported_cost(ctx) is None


def _price_calc(total: float) -> MagicMock:
    """Build a stand-in PriceCalculation with the given total_price."""
    m = MagicMock()
    m.total_price = Decimal(str(total))
    return m


def test_genai_prices_basic_input_output() -> None:
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["usage"] = usage
        captured["model_ref"] = model_ref
        captured["provider_id"] = provider_id
        return _price_calc(0.0075)

    with patch("fireflyframework_agentic.observability.cost_resolvers.calc_price", side_effect=fake_calc):
        cost = genai_prices_cost(
            CostContext(
                model="openai:gpt-4o",
                input_tokens=1000,
                output_tokens=500,
            )
        )
    assert cost == pytest.approx(0.0075)
    assert captured["model_ref"] == "gpt-4o"
    assert captured["provider_id"] == "openai"
    # No cache, no reasoning: Usage.input_tokens should equal ctx.input_tokens.
    assert captured["usage"].input_tokens == 1000
    assert captured["usage"].output_tokens == 500


def test_genai_prices_folds_cache_tokens_into_usage_input() -> None:
    """Usage.input_tokens must be TOTAL prompt (uncached + cache_creation + cache_read).

    genai-prices subtracts cache portions internally; passing only the
    uncached portion makes it raise ValueError.
    """
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["usage"] = usage
        return _price_calc(0.0)

    ctx = CostContext(
        model="anthropic:claude-3-5-sonnet-latest",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=1000,
        cache_read_tokens=5000,
    )
    with patch("fireflyframework_agentic.observability.cost_resolvers.calc_price", side_effect=fake_calc):
        genai_prices_cost(ctx)
    u = captured["usage"]
    assert u.input_tokens == 100 + 1000 + 5000
    assert u.cache_write_tokens == 1000
    assert u.cache_read_tokens == 5000


def test_genai_prices_folds_reasoning_into_output() -> None:
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["usage"] = usage
        return _price_calc(0.0)

    ctx = CostContext(model="openai:o3", input_tokens=100, output_tokens=50, reasoning_tokens=200)
    with patch("fireflyframework_agentic.observability.cost_resolvers.calc_price", side_effect=fake_calc):
        genai_prices_cost(ctx)
    assert captured["usage"].output_tokens == 50 + 200


def test_genai_prices_unknown_model_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    _resolvers_mod._UNKNOWN_MODEL_WARNED.clear()
    with (
        patch("fireflyframework_agentic.observability.cost_resolvers.calc_price", side_effect=LookupError("not found")),
        caplog.at_level("WARNING"),
    ):
        assert genai_prices_cost(CostContext(model="unknown:foo", input_tokens=1, output_tokens=1)) is None
        assert genai_prices_cost(CostContext(model="unknown:foo", input_tokens=1, output_tokens=1)) is None
    warnings = [r for r in caplog.records if "unknown" in r.message.lower()]
    assert len(warnings) == 1  # deduplicated


def test_genai_prices_swallows_other_exceptions() -> None:
    with patch("fireflyframework_agentic.observability.cost_resolvers.calc_price", side_effect=RuntimeError("boom")):
        assert genai_prices_cost(CostContext(model="x", input_tokens=1, output_tokens=1)) is None


def test_genai_prices_no_provider_prefix_passes_none_provider() -> None:
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["model_ref"] = model_ref
        captured["provider_id"] = provider_id
        return _price_calc(0.0)

    with patch("fireflyframework_agentic.observability.cost_resolvers.calc_price", side_effect=fake_calc):
        genai_prices_cost(CostContext(model="gpt-4o", input_tokens=1, output_tokens=1))
    assert captured["model_ref"] == "gpt-4o"
    assert captured["provider_id"] is None


def test_resolve_cost_uses_first_non_none() -> None:
    def always_one(_ctx: CostContext) -> float | None:
        return 1.23

    def never_called(_ctx: CostContext) -> float | None:
        raise AssertionError("should not be called")

    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    assert resolve_cost(ctx, [always_one, never_called]) == 1.23


def test_resolve_cost_falls_through_to_next() -> None:
    def abstain(_ctx: CostContext) -> float | None:
        return None

    def answer(_ctx: CostContext) -> float | None:
        return 7.0

    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    assert resolve_cost(ctx, [abstain, answer]) == 7.0


def test_resolve_cost_all_none_returns_zero() -> None:
    def abstain(_ctx: CostContext) -> float | None:
        return None

    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    assert resolve_cost(ctx, [abstain, abstain]) == 0.0


def test_resolve_cost_default_chain_used_when_none() -> None:
    # Default chain = [provider_reported_cost, genai_prices_cost].
    # With a payload carrying cost, provider_reported_cost wins; genai-prices
    # is not consulted (no patch needed).
    ctx = CostContext(
        model="openrouter:x",
        input_tokens=1,
        output_tokens=1,
        provider_payload={"usage": {"cost": 0.42}},
    )
    assert resolve_cost(ctx) == 0.42


def test_default_resolvers_is_tuple() -> None:
    assert isinstance(DEFAULT_RESOLVERS, tuple)
    assert len(DEFAULT_RESOLVERS) == 2
