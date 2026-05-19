# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for agent delegation strategies and the routing API."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.delegation import (
    Candidate,
    CapabilityStrategy,
    ChainStrategy,
    ContentBasedStrategy,
    CostAwareStrategy,
    DelegationRouter,
    DelegationStrategy,
    FallbackStrategy,
    RoundRobinStrategy,
    RoutingDecision,
    WeightedStrategy,
)
from fireflyframework_agentic.exceptions import DelegationError
from fireflyframework_agentic.observability.cost_resolvers import (
    CostContext,
    UnknownModelCostError,
)

# -- Test helpers ------------------------------------------------------------


class _FakeAgent:
    """Minimal stand-in for FireflyAgent for routing unit tests."""

    def __init__(
        self,
        name: str,
        model_name: str = "",
        tags: tuple[str, ...] = (),
        description: str = "",
    ) -> None:
        self.name = name
        self.model_name = model_name
        self.tags = tags
        self.description = description
        self.run_calls: list[tuple[Any, Any]] = []

    async def run(self, prompt: Any, *, deps: Any = None, **kwargs: Any) -> str:
        self.run_calls.append((prompt, deps))
        return f"ran:{self.name}"


def _fake(
    name: str,
    model_name: str = "",
    tags: tuple[str, ...] = (),
    description: str = "",
) -> FireflyAgent[Any, Any]:
    """Create a `_FakeAgent` typed as `FireflyAgent` for routing tests."""
    return cast(
        "FireflyAgent[Any, Any]",
        _FakeAgent(name=name, model_name=model_name, tags=tags, description=description),
    )


def _fixed_cost(model_to_cost: dict[str, float]):
    """Build a deterministic cost resolver from a model→cost map."""

    def resolver(ctx: CostContext) -> float | None:
        return model_to_cost.get(ctx.model)

    return resolver


# -- RoutingDecision --------------------------------------------------------


def test_routing_decision_chosen_raises_on_empty():
    decision = RoutingDecision(candidates=(), strategy="X", metadata={})
    with pytest.raises(DelegationError):
        _ = decision.chosen


def test_routing_decision_chosen_preserves_order():
    a, b = _fake("a"), _fake("b")
    decision = RoutingDecision(
        candidates=(
            Candidate(agent=a, score=0.9, reason=""),
            Candidate(agent=b, score=0.7, reason=""),
        ),
        strategy="X",
        metadata={},
    )
    assert decision.chosen is a


# -- RoundRobinStrategy -----------------------------------------------------


@pytest.mark.asyncio
async def test_round_robin_cycles_through_agents():
    strategy = RoundRobinStrategy()
    agents = [_fake("a"), _fake("b"), _fake("c")]
    chosen = []
    for _ in range(6):
        decision = await strategy.decide(agents, "prompt")
        assert len(decision.candidates) == 1
        assert decision.candidates[0].score == 1.0
        assert decision.candidates[0].reason == "round-robin turn"
        chosen.append(decision.candidates[0].agent.name)
    assert chosen == ["a", "b", "c", "a", "b", "c"]


@pytest.mark.asyncio
async def test_round_robin_empty_pool_returns_empty_decision():
    strategy = RoundRobinStrategy()
    decision = await strategy.decide([], "prompt")
    assert decision.candidates == ()
    assert decision.strategy == "RoundRobinStrategy"


@pytest.mark.asyncio
async def test_round_robin_metadata_has_turn():
    strategy = RoundRobinStrategy()
    agents = [_fake("a"), _fake("b")]
    d1 = await strategy.decide(agents, "p")
    d2 = await strategy.decide(agents, "p")
    assert d1.metadata["turn"] == 0
    assert d2.metadata["turn"] == 1


# -- CapabilityStrategy ----------------------------------------------------


@pytest.mark.asyncio
async def test_capability_returns_all_matches():
    strategy = CapabilityStrategy("vision")
    agents = [
        _fake("a", tags=("vision", "fast")),
        _fake("b", tags=("text",)),
        _fake("c", tags=("vision",)),
    ]
    decision = await strategy.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["a", "c"]
    assert all(c.score == 1.0 for c in decision.candidates)


@pytest.mark.asyncio
async def test_capability_no_match_returns_empty():
    strategy = CapabilityStrategy("vision")
    agents = [_fake("a", tags=("text",))]
    decision = await strategy.decide(agents, "p")
    assert decision.candidates == ()


@pytest.mark.asyncio
async def test_capability_empty_pool_returns_empty():
    strategy = CapabilityStrategy("vision")
    decision = await strategy.decide([], "p")
    assert decision.candidates == ()


# -- ContentBasedStrategy --------------------------------------------------


@pytest.mark.asyncio
async def test_content_based_single_agent_skips_llm():
    strategy = ContentBasedStrategy()
    agents = [_fake("only")]
    decision = await strategy.decide(agents, "hello")
    assert len(decision.candidates) == 1
    assert decision.candidates[0].agent.name == "only"
    assert decision.candidates[0].score == 1.0


@pytest.mark.asyncio
async def test_content_based_empty_returns_empty():
    strategy = ContentBasedStrategy()
    decision = await strategy.decide([], "hello")
    assert decision.candidates == ()


@pytest.mark.asyncio
async def test_content_based_llm_failure_returns_empty():
    """LLM failure must NOT silently return first agent — returns empty."""
    strategy = ContentBasedStrategy(model="nonexistent:model")
    agents = [_fake("first"), _fake("second")]
    decision = await strategy.decide(agents, "hello")
    assert decision.candidates == ()
    assert decision.metadata.get("error") == "llm_failure"


# -- CostAwareStrategy ----------------------------------------------------


@pytest.mark.asyncio
async def test_cost_aware_single_agent_score_one():
    strategy = CostAwareStrategy(resolvers=[_fixed_cost({"m1": 0.001})])
    agents = [_fake("only", model_name="m1")]
    decision = await strategy.decide(agents, "p")
    assert len(decision.candidates) == 1
    assert decision.candidates[0].score == 1.0


@pytest.mark.asyncio
async def test_cost_aware_pool_relative_normalisation():
    strategy = CostAwareStrategy(resolvers=[_fixed_cost({"cheap": 0.001, "mid": 0.002, "exp": 0.003})])
    agents = [
        _fake("exp", model_name="exp"),
        _fake("cheap", model_name="cheap"),
        _fake("mid", model_name="mid"),
    ]
    decision = await strategy.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["cheap", "mid", "exp"]
    scores = {c.agent.name: c.score for c in decision.candidates}
    assert scores["cheap"] == pytest.approx(1.0)
    assert scores["mid"] == pytest.approx(0.5)
    assert scores["exp"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_cost_aware_all_equal_costs_all_score_one():
    strategy = CostAwareStrategy(resolvers=[_fixed_cost({"m": 0.005})])
    agents = [
        _fake("a", model_name="m"),
        _fake("b", model_name="m"),
    ]
    decision = await strategy.decide(agents, "p")
    assert all(c.score == 1.0 for c in decision.candidates)


@pytest.mark.asyncio
async def test_cost_aware_on_unknown_skip():
    strategy = CostAwareStrategy(
        resolvers=[_fixed_cost({"known": 0.001})],
        on_unknown="skip",
    )
    agents = [
        _fake("known", model_name="known"),
        _fake("unknown", model_name="never-priced"),
    ]
    decision = await strategy.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["known"]


@pytest.mark.asyncio
async def test_cost_aware_on_unknown_lowest():
    strategy = CostAwareStrategy(
        resolvers=[_fixed_cost({"known": 0.001})],
        on_unknown="lowest",
    )
    agents = [
        _fake("known", model_name="known"),
        _fake("unknown", model_name="never-priced"),
    ]
    decision = await strategy.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["known", "unknown"]
    by_name = {c.agent.name: c.score for c in decision.candidates}
    assert by_name["known"] == 1.0
    assert by_name["unknown"] == 0.0


@pytest.mark.asyncio
async def test_cost_aware_on_unknown_raise():
    strategy = CostAwareStrategy(
        resolvers=[_fixed_cost({"known": 0.001})],
        on_unknown="raise",
    )
    agents = [
        _fake("known", model_name="known"),
        _fake("unknown", model_name="never-priced"),
    ]
    with pytest.raises(UnknownModelCostError):
        await strategy.decide(agents, "p")


@pytest.mark.asyncio
async def test_cost_aware_empty_pool_returns_empty():
    decision = await CostAwareStrategy().decide([], "p")
    assert decision.candidates == ()


@pytest.mark.asyncio
async def test_cost_aware_resolver_chain_override_used():
    """Custom resolvers are honoured (not just DEFAULT_RESOLVERS)."""
    calls: list[str] = []

    def tracking_resolver(ctx: CostContext) -> float | None:
        calls.append(ctx.model)
        return 0.01

    strategy = CostAwareStrategy(resolvers=[tracking_resolver])
    agents = [_fake("a", model_name="x"), _fake("b", model_name="y")]
    await strategy.decide(agents, "p")
    assert calls == ["x", "y"]


# -- ChainStrategy ---------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_narrows_across_stages():
    """Capability narrows, then CostAware ranks the survivors."""
    cap = CapabilityStrategy("vision")
    cost = CostAwareStrategy(resolvers=[_fixed_cost({"cheap": 0.001, "exp": 0.01})])
    chain = ChainStrategy(cap, cost)
    agents = [
        _fake("a", model_name="exp", tags=("vision",)),
        _fake("b", model_name="cheap", tags=("vision",)),
        _fake("c", model_name="cheap", tags=("text",)),
    ]
    decision = await chain.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["b", "a"]  # c excluded by capability stage.
    assert decision.strategy == "ChainStrategy"


@pytest.mark.asyncio
async def test_chain_short_circuits_on_empty_intermediate():
    cap = CapabilityStrategy("vision")
    rr = RoundRobinStrategy()
    chain = ChainStrategy(cap, rr)
    agents = [_fake("a", tags=("text",))]
    decision = await chain.decide(agents, "p")
    assert decision.candidates == ()
    assert decision.metadata.get("short_circuited_at") == "CapabilityStrategy"


@pytest.mark.asyncio
async def test_chain_no_stages_returns_empty():
    decision = await ChainStrategy().decide([_fake("a")], "p")
    assert decision.candidates == ()


# -- FallbackStrategy ------------------------------------------------------


class _EmptyStrategy:
    async def decide(self, agents, prompt, **kwargs):
        return RoutingDecision(candidates=(), strategy="Empty", metadata={})


class _RaisingStrategy:
    async def decide(self, agents, prompt, **kwargs):
        raise DelegationError("nope")


@pytest.mark.asyncio
async def test_fallback_returns_first_non_empty():
    rr = RoundRobinStrategy()
    fb = FallbackStrategy(_EmptyStrategy(), rr)
    agents = [_fake("a")]
    decision = await fb.decide(agents, "p")
    assert len(decision.candidates) == 1
    assert decision.candidates[0].agent.name == "a"
    assert decision.metadata["chosen_strategy"] == "RoundRobinStrategy"


@pytest.mark.asyncio
async def test_fallback_skips_on_delegation_error():
    rr = RoundRobinStrategy()
    fb = FallbackStrategy(_RaisingStrategy(), rr)
    agents = [_fake("a")]
    decision = await fb.decide(agents, "p")
    assert decision.candidates[0].agent.name == "a"


@pytest.mark.asyncio
async def test_fallback_all_empty_returns_empty():
    fb = FallbackStrategy(_EmptyStrategy(), _EmptyStrategy())
    decision = await fb.decide([_fake("a")], "p")
    assert decision.candidates == ()
    assert decision.metadata["tried"] == ["_EmptyStrategy", "_EmptyStrategy"]


# -- WeightedStrategy ------------------------------------------------------


class _ScriptedStrategy:
    """Returns a pre-baked decision over the given agents/scores."""

    def __init__(self, scores_by_name: dict[str, float]) -> None:
        self._scores = scores_by_name

    async def decide(self, agents, prompt, **kwargs):
        candidates = tuple(
            Candidate(agent=a, score=self._scores[a.name], reason="scripted") for a in agents if a.name in self._scores
        )
        return RoutingDecision(candidates=candidates, strategy="Scripted", metadata={})


@pytest.mark.asyncio
async def test_weighted_normalises_weights_internally():
    """Weights 3 and 1 should normalise to 0.75 and 0.25 — same result whether passed as (3,1) or (0.75,0.25)."""
    s1 = _ScriptedStrategy({"a": 1.0, "b": 0.0})
    s2 = _ScriptedStrategy({"a": 0.0, "b": 1.0})
    agents = [_fake("a"), _fake("b")]

    w_raw = WeightedStrategy(strategies=[(s1, 3.0), (s2, 1.0)])
    w_norm = WeightedStrategy(strategies=[(s1, 0.75), (s2, 0.25)])

    d_raw = await w_raw.decide(agents, "p")
    d_norm = await w_norm.decide(agents, "p")
    raw_scores = {c.agent.name: c.score for c in d_raw.candidates}
    norm_scores = {c.agent.name: c.score for c in d_norm.candidates}
    assert raw_scores == pytest.approx(norm_scores)
    assert raw_scores["a"] == pytest.approx(0.75)
    assert raw_scores["b"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_weighted_absent_agent_contributes_zero():
    s1 = _ScriptedStrategy({"a": 1.0})  # b omitted.
    s2 = _ScriptedStrategy({"a": 1.0, "b": 1.0})
    agents = [_fake("a"), _fake("b")]
    w = WeightedStrategy(strategies=[(s1, 1.0), (s2, 1.0)])
    decision = await w.decide(agents, "p")
    by_name = {c.agent.name: c.score for c in decision.candidates}
    # a: (1.0*0.5 + 1.0*0.5) = 1.0; b: (0*0.5 + 1.0*0.5) = 0.5.
    assert by_name["a"] == pytest.approx(1.0)
    assert by_name["b"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_weighted_min_score_filter():
    s1 = _ScriptedStrategy({"a": 1.0, "b": 0.1})
    agents = [_fake("a"), _fake("b")]
    w = WeightedStrategy(strategies=[(s1, 1.0)], min_score=0.5)
    decision = await w.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["a"]


@pytest.mark.asyncio
async def test_weighted_scores_in_unit_range():
    s1 = _ScriptedStrategy({"a": 1.0, "b": 0.4})
    s2 = _ScriptedStrategy({"a": 0.3, "b": 0.9})
    w = WeightedStrategy(strategies=[(s1, 2.0), (s2, 1.0)])
    agents = [_fake("a"), _fake("b")]
    decision = await w.decide(agents, "p")
    for c in decision.candidates:
        assert 0.0 <= c.score <= 1.0


@pytest.mark.asyncio
async def test_weighted_ranks_descending():
    s1 = _ScriptedStrategy({"a": 0.2, "b": 0.9})
    w = WeightedStrategy(strategies=[(s1, 1.0)])
    agents = [_fake("a"), _fake("b")]
    decision = await w.decide(agents, "p")
    names = [c.agent.name for c in decision.candidates]
    assert names == ["b", "a"]


# -- DelegationRouter ------------------------------------------------------


@pytest.mark.asyncio
async def test_router_decide_is_pure_no_run():
    """decide() does not execute the agent."""
    a = _fake("a")
    router = DelegationRouter([a], RoundRobinStrategy())
    decision = await router.decide("p")
    assert decision.candidates[0].agent is a
    assert a.run_calls == []


@pytest.mark.asyncio
async def test_router_execute_runs_chosen_agent():
    a = _fake("a")
    router = DelegationRouter([a], RoundRobinStrategy())
    decision = await router.decide("p")
    out = await router.execute(decision, "the-prompt", deps="d")
    assert out == "ran:a"
    assert a.run_calls == [("the-prompt", "d")]


@pytest.mark.asyncio
async def test_router_execute_raises_on_empty_decision():
    a = _fake("a", tags=("text",))
    router = DelegationRouter([a], CapabilityStrategy("vision"))
    decision = await router.decide("p")
    assert decision.candidates == ()
    with pytest.raises(DelegationError):
        await router.execute(decision, "p")


@pytest.mark.asyncio
async def test_router_route_keeps_existing_signature():
    a = _fake("a")
    router = DelegationRouter([a], RoundRobinStrategy())
    out = await router.route("hello", deps="d")
    assert out == "ran:a"


@pytest.mark.asyncio
async def test_router_execute_forks_memory_when_attached():
    """If memory is attached, the chosen agent's memory is replaced by a forked scope."""

    class _Fork:
        def __init__(self, scope_id: str) -> None:
            self.scope_id = scope_id

    class _Mem:
        def __init__(self) -> None:
            self.forks: list[str] = []

        def fork(self, *, working_scope_id: str) -> _Fork:
            self.forks.append(working_scope_id)
            return _Fork(working_scope_id)

    a = _fake("a")
    a.memory = None  # attribute must exist for the fork branch to run.
    mem = _Mem()
    router = DelegationRouter([a], RoundRobinStrategy(), memory=mem)
    await router.route("p")
    assert mem.forks == ["delegation:a"]
    assert isinstance(a.memory, _Fork)


@pytest.mark.asyncio
async def test_router_decide_does_not_fork_memory():
    """decide() must NOT fork memory — only execute() does."""

    class _Mem:
        def __init__(self) -> None:
            self.forks: list[str] = []

        def fork(self, *, working_scope_id: str):
            self.forks.append(working_scope_id)
            return None

    a = _fake("a")
    a.memory = None
    mem = _Mem()
    router = DelegationRouter([a], RoundRobinStrategy(), memory=mem)
    await router.decide("p")
    assert mem.forks == []


# -- OTel decision event ---------------------------------------------------


@pytest.mark.asyncio
async def test_router_emits_otel_decision_event(monkeypatch):
    """One ``firefly.routing.decision`` span per decide() with expected attrs."""
    from contextlib import contextmanager

    from fireflyframework_agentic.agents import delegation as delegation_mod

    captured: list[tuple[str, dict[str, Any]]] = []

    class _FakeSpan:
        def set_attribute(self, *_args, **_kwargs):  # pragma: no cover - unused.
            pass

    @contextmanager
    def fake_custom_span(name: str, **attributes: Any):
        captured.append((name, dict(attributes)))
        yield _FakeSpan()

    monkeypatch.setattr(delegation_mod.default_tracer, "custom_span", fake_custom_span)

    a = _fake("a")
    router = DelegationRouter([a], RoundRobinStrategy())
    await router.decide("p")

    assert len(captured) == 1
    name, attrs = captured[0]
    assert name == "firefly.routing.decision"
    assert attrs["strategy"] == "RoundRobinStrategy"
    assert attrs["candidates_count"] == 1
    assert attrs["chosen_agent"] == "a"
    assert attrs["chosen_score"] == 1.0
    assert "duration_ms" in attrs
    # routing.turn flattened from metadata; OTel-safe primitive.
    assert attrs["routing.turn"] == 0
    # candidates_json must be a JSON string.
    parsed = json.loads(attrs["routing.candidates_json"])
    assert parsed[0]["agent"] == "a"
    assert parsed[0]["score"] == 1.0


@pytest.mark.asyncio
async def test_router_emits_one_event_even_for_combinator(monkeypatch):
    """Combinators don't emit their own events — only the top-level router does."""
    from contextlib import contextmanager

    from fireflyframework_agentic.agents import delegation as delegation_mod

    captured: list[str] = []

    @contextmanager
    def fake_custom_span(name: str, **attributes: Any):
        captured.append(name)
        yield None

    monkeypatch.setattr(delegation_mod.default_tracer, "custom_span", fake_custom_span)

    chain = ChainStrategy(RoundRobinStrategy(), RoundRobinStrategy())
    router = DelegationRouter([_fake("a")], chain)
    await router.decide("p")
    assert captured == ["firefly.routing.decision"]


@pytest.mark.asyncio
async def test_router_event_metadata_coerced_for_otel(monkeypatch):
    """Non-trivial metadata values are JSON-serialised for OTel attribute compatibility."""
    from contextlib import contextmanager

    from fireflyframework_agentic.agents import delegation as delegation_mod

    captured: list[dict[str, Any]] = []

    @contextmanager
    def fake_custom_span(name: str, **attributes: Any):
        captured.append(dict(attributes))
        yield None

    monkeypatch.setattr(delegation_mod.default_tracer, "custom_span", fake_custom_span)

    class _MetadataStrategy:
        async def decide(self, agents, prompt, **kwargs):
            return RoutingDecision(
                candidates=(Candidate(agent=agents[0], score=1.0, reason=""),),
                strategy="MetadataStrategy",
                metadata={"complex": {"nested": [1, 2]}, "flat": 7},
            )

    router = DelegationRouter([_fake("a")], _MetadataStrategy())
    await router.decide("p")
    attrs = captured[0]
    # Flat primitives stay primitive; nested mappings become JSON strings.
    assert attrs["routing.flat"] == 7
    assert isinstance(attrs["routing.complex"], str)
    assert json.loads(attrs["routing.complex"]) == {"nested": [1, 2]}


# -- Protocol conformance --------------------------------------------------


def test_all_strategies_satisfy_protocol():
    for s in [
        RoundRobinStrategy(),
        CapabilityStrategy("x"),
        ContentBasedStrategy(),
        CostAwareStrategy(),
        ChainStrategy(),
        FallbackStrategy(),
        WeightedStrategy(strategies=[(RoundRobinStrategy(), 1.0)]),
    ]:
        assert isinstance(s, DelegationStrategy)
