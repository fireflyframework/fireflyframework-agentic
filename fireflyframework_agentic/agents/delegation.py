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

"""Multi-agent delegation with pluggable, composable routing strategies.

A :class:`DelegationRouter` accepts a pool of agents and a
:class:`DelegationStrategy` that decides which agent handles a given input.
Strategies return :class:`RoutingDecision` objects: ranked, scored candidate
lists with free-form metadata. Decisions can be inspected, cached, replayed
or executed via the router.

Four built-in strategies (:class:`RoundRobinStrategy`,
:class:`CapabilityStrategy`, :class:`ContentBasedStrategy`,
:class:`CostAwareStrategy`) cover the common cases. Three combinators
(:class:`ChainStrategy`, :class:`FallbackStrategy`,
:class:`WeightedStrategy`) compose them without subclassing.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic_ai import Agent as PydanticAgent

from fireflyframework_agentic.exceptions import DelegationError
from fireflyframework_agentic.observability.cost_resolvers import (
    DEFAULT_RESOLVERS,
    CostContext,
    CostFn,
    UnknownModelCostError,
    resolve_cost,
)
from fireflyframework_agentic.observability.tracer import default_tracer
from fireflyframework_agentic.types import UserContent

if TYPE_CHECKING:
    from fireflyframework_agentic.agents.base import FireflyAgent
    from fireflyframework_agentic.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


# -- Core types --------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One scored candidate produced by a :class:`DelegationStrategy`.

    Attributes:
        agent: The candidate agent.
        score: Normalised score in ``[0.0, 1.0]``; higher is better.
        reason: Short human-readable explanation of why this score.
            Treat as display-only — do not parse.
        metadata: Optional structured per-candidate data (e.g. component
            scores from :class:`WeightedStrategy`). Mirrors the role of
            :attr:`RoutingDecision.metadata` at the candidate level.
    """

    agent: FireflyAgent[Any, Any]
    score: float
    reason: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingDecision:
    """The output of :meth:`DelegationStrategy.decide`.

    Attributes:
        candidates: Ranked best-first; may be empty (meaning "no opinion").
        strategy: Class name of the strategy that produced the decision.
        metadata: Free-form mapping flattened into the OTel decision event
            under the ``routing.`` prefix.
    """

    candidates: tuple[Candidate, ...]
    strategy: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def chosen(self) -> FireflyAgent[Any, Any]:
        """Return the top candidate's agent.

        Raises:
            DelegationError: If the decision is empty.
        """
        if not self.candidates:
            raise DelegationError("Empty routing decision")
        return self.candidates[0].agent

    @classmethod
    def empty(cls, strategy: str, **metadata: Any) -> RoutingDecision:
        """Build an empty (no-opinion) decision tagged with *strategy*."""
        return cls(candidates=(), strategy=strategy, metadata=metadata)


@runtime_checkable
class DelegationStrategy(Protocol):
    """Protocol for agent selection strategies.

    Implement this protocol to create custom routing logic. The framework
    ships with :class:`RoundRobinStrategy`, :class:`CapabilityStrategy`,
    :class:`ContentBasedStrategy`, and :class:`CostAwareStrategy`, plus
    three combinators (:class:`ChainStrategy`, :class:`FallbackStrategy`,
    :class:`WeightedStrategy`).
    """

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Produce a routing decision for *prompt* over *agents*."""
        ...


# -- Built-in strategies -----------------------------------------------------


class RoundRobinStrategy:
    """Cycle through agents in order, wrapping back to the first after the last.

    Returns a 1-element decision with ``score=1.0``. Empty pool yields an
    empty decision (no exception); the router raises only when
    :meth:`DelegationRouter.execute` is called on an empty decision.
    """

    def __init__(self) -> None:
        self._cycle: itertools.cycle[FireflyAgent[Any, Any]] | None = None
        self._last_ids: tuple[int, ...] = ()
        self._lock = asyncio.Lock()

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Pick the next agent in round-robin order.

        Resets the cursor whenever the pool's object identities change.
        Inside a combinator that passes a freshly-built sub-pool every
        call (e.g. :class:`ChainStrategy`), the cycle effectively resets
        each turn — call this strategy directly from the router for
        stateful cycling.
        """
        del prompt, kwargs
        if not agents:
            return RoutingDecision.empty(type(self).__name__)
        ids = tuple(id(a) for a in agents)
        # Strategies are shared across a router and may run concurrently; guard
        # the cursor so concurrent calls don't race it.
        async with self._lock:
            if self._cycle is None or ids != self._last_ids:
                self._cycle = itertools.cycle(agents)
                self._last_ids = ids
            agent = next(self._cycle)
        candidate = Candidate(agent=agent, score=1.0, reason="round-robin turn")
        return RoutingDecision(
            candidates=(candidate,),
            strategy=type(self).__name__,
            metadata={},
        )


class CapabilityStrategy:
    """Select all agents whose tags include a required capability.

    Returns every matching agent with ``score=1.0``; non-matching agents
    are omitted. No-match yields an empty decision (composable with
    :class:`FallbackStrategy`).

    Parameters:
        required_tag: The tag that selected agents must possess.
    """

    def __init__(self, required_tag: str) -> None:
        self._tag = required_tag

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Return all agents tagged with the required capability."""
        del prompt, kwargs
        matches: list[Candidate] = []
        for agent in agents:
            tags = getattr(agent, "tags", None)
            if tags is not None and self._tag in tags:
                matches.append(Candidate(agent=agent, score=1.0, reason=f"has tag '{self._tag}'"))
        return RoutingDecision(
            candidates=tuple(matches),
            strategy=type(self).__name__,
            metadata={"required_tag": self._tag},
        )


class ContentBasedStrategy:
    """Select an agent by asking an LLM which is best suited for the prompt.

    The strategy builds a short description of each agent (from its
    ``name`` and ``description`` attributes) and asks the routing model
    to pick the single best-suited index.

    Returns a one-candidate decision with ``score=1.0`` (the LLM is not
    asked for ranks or confidences, so no per-agent ranking is exposed
    — treat blends via :class:`WeightedStrategy` accordingly). On LLM
    failure, non-numeric response, or out-of-range index the strategy
    returns an empty decision so :class:`FallbackStrategy` can take
    over (it does NOT silently return the first agent).

    Parameters:
        model: A *pydantic-ai* model name used for the routing decision
            (e.g. ``"openai:gpt-4o-mini"``). Kept lightweight by design.
    """

    def __init__(self, model: str = "openai:gpt-4o-mini") -> None:
        self._model = model
        # Lazily-built, reused router agent (the model is fixed for the
        # strategy's lifetime, so one instance serves every routing call).
        self._router: PydanticAgent | None = None
        self._router_lock = asyncio.Lock()

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Ask the routing LLM to pick the best agent for *prompt*."""
        name = type(self).__name__
        if not agents:
            return RoutingDecision.empty(name)
        if len(agents) == 1:
            return RoutingDecision(
                candidates=(Candidate(agent=agents[0], score=1.0, reason="only candidate"),),
                strategy=name,
                metadata={"singleton": True},
            )

        descriptions: list[str] = []
        for i, agent in enumerate(agents):
            agent_name = getattr(agent, "name", f"agent_{i}")
            desc = getattr(agent, "description", "")
            descriptions.append(f"{i}: {agent_name} - {desc or 'no description'}")

        prompt_text = prompt if isinstance(prompt, str) else str(prompt)
        routing_prompt = (
            "You are a routing assistant. Given the user prompt and the list of "
            "available agents below, respond with ONLY the index number of the "
            "agent best suited to handle the prompt.\n\n"
            f"User prompt: {prompt_text[:500]}\n\n"
            "Available agents:\n" + "\n".join(descriptions)
        )

        try:
            # Guard the lazy build so concurrent first calls don't each
            # construct (and leak) a router agent.
            if self._router is None:
                async with self._router_lock:
                    if self._router is None:
                        self._router = PydanticAgent(self._model, instructions="You pick the best agent.")
            result = await self._router.run(routing_prompt)
        except Exception:
            logger.warning("Content-based routing LLM call failed", exc_info=True)
            return RoutingDecision.empty(name, error="llm_failure")

        idx_str = result.output.strip()
        digits = "".join(c for c in idx_str if c.isdigit())[:3]
        if not digits:
            logger.warning("Content-based routing got non-numeric response: %r", idx_str[:50])
            return RoutingDecision.empty(name, error="non_numeric_response")

        idx = int(digits)
        if not (0 <= idx < len(agents)):
            logger.warning("Content-based routing returned out-of-range index %d", idx)
            return RoutingDecision.empty(name, error="out_of_range")

        # Single chosen agent with full confidence; no per-other ranking given.
        chosen = Candidate(agent=agents[idx], score=1.0, reason=f"LLM picked index {idx}")
        return RoutingDecision(
            candidates=(chosen,),
            strategy=type(self).__name__,
            metadata={"llm_index": idx, "model": self._model},
        )


class CostAwareStrategy:
    """Rank agents by per-call cost via the project's cost resolver chain.

    Cost per agent is computed with
    :func:`fireflyframework_agentic.observability.cost_resolvers.resolve_cost`
    against a synthetic :class:`CostContext` representing a typical call.
    Scores are pool-relative linear normalisations:
    ``score = 1.0 - (cost - min) / (max - min)``. All-equal costs (or a
    single agent) score ``1.0``.

    Parameters:
        sample: Representative :class:`CostContext` used to price each
            agent. Only the token counts are read; the ``model`` field is
            overwritten per agent. Defaults to ``1000`` input / ``500``
            output tokens, everything else zero — fine for relative
            ranking, override if cache or reasoning tokens dominate your
            workload.
        resolvers: Optional cost resolver chain. Defaults to
            :data:`DEFAULT_RESOLVERS`.
        on_unknown: How to handle agents the resolver chain cannot price.
            ``"skip"`` omits, ``"lowest"`` includes with score ``0.0``,
            ``"raise"`` raises :class:`UnknownModelCostError`.
    """

    _DEFAULT_SAMPLE = CostContext(model="", input_tokens=1000, output_tokens=500)

    def __init__(
        self,
        *,
        sample: CostContext | None = None,
        resolvers: Sequence[CostFn] | None = None,
        on_unknown: Literal["skip", "lowest", "raise"] = "skip",
    ) -> None:
        self._sample = sample if sample is not None else self._DEFAULT_SAMPLE
        self._resolvers = tuple(resolvers) if resolvers is not None else DEFAULT_RESOLVERS
        self._on_unknown = on_unknown

    def _agent_cost(self, agent: FireflyAgent[Any, Any]) -> float | None:
        """Compute the synthetic per-call cost for *agent*."""
        if not agent.model_identifier:
            return None
        ctx = replace(self._sample, model=agent.model_identifier)
        # Force non-strict so we control the unknown-model branch ourselves.
        return resolve_cost(ctx, resolvers=self._resolvers, strict=False)

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Rank agents by ascending cost (cheapest first)."""
        if not agents:
            return RoutingDecision.empty(type(self).__name__)

        priced: list[tuple[FireflyAgent[Any, Any], float]] = []
        unknown: list[FireflyAgent[Any, Any]] = []
        for agent in agents:
            cost = self._agent_cost(agent)
            if cost is None:
                if self._on_unknown == "raise":
                    raise UnknownModelCostError(agent.model_identifier or "<unknown>")
                unknown.append(agent)
            else:
                priced.append((agent, cost))

        # Priced agents are normalised to [0.0, 1.0]; the most expensive priced
        # agent scores 0.0. Unknown agents (under on_unknown="lowest") also score
        # 0.0 — same numeric value, different meaning. To preserve the
        # "priced beats unknown" intent without leaking a sentinel score outside
        # the [0, 1] contract, sort priced and unknown independently and then
        # concatenate: ordering encodes preference, score stays honest about
        # confidence. Consumers blending via WeightedStrategy still see 0.0 for
        # both buckets — per-Candidate metadata (not score) is the right place
        # to disambiguate them if needed.
        priced_candidates: list[Candidate] = []
        if priced:
            costs = [c for _, c in priced]
            lo, hi = min(costs), max(costs)
            span = hi - lo
            for agent, cost in priced:
                score = 1.0 if span == 0 else 1.0 - (cost - lo) / span
                priced_candidates.append(
                    Candidate(
                        agent=agent,
                        score=score,
                        reason=f"cost ${cost:.6f} (pool min ${lo:.6f}, max ${hi:.6f})",
                    )
                )
            priced_candidates.sort(key=lambda c: c.score, reverse=True)

        unknown_candidates: list[Candidate] = []
        if self._on_unknown == "lowest":
            unknown_candidates = [
                Candidate(agent=agent, score=0.0, reason="cost unknown (on_unknown='lowest')") for agent in unknown
            ]

        return RoutingDecision(
            candidates=tuple(priced_candidates + unknown_candidates),
            strategy=type(self).__name__,
            metadata={
                "priced_count": len(priced),
                "unknown_count": len(unknown),
                "on_unknown": self._on_unknown,
            },
        )


# -- Combinators -------------------------------------------------------------


class ChainStrategy:
    """Sequential narrowing across stages.

    Each stage receives the surviving candidate agents from the previous
    stage's decision (not the full pool). Final stage's scores are
    returned. An empty intermediate decision short-circuits to an empty
    result.

    Parameters:
        *stages: Strategies to apply in order.
    """

    def __init__(self, *stages: DelegationStrategy) -> None:
        self._stages: tuple[DelegationStrategy, ...] = stages

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Apply stages sequentially, narrowing the candidate pool each step."""
        name = type(self).__name__
        if not self._stages:
            return RoutingDecision.empty(name)

        current_agents: Sequence[FireflyAgent[Any, Any]] = list(agents)
        last_decision: RoutingDecision | None = None
        stage_names: list[str] = []
        for stage in self._stages:
            stage_names.append(type(stage).__name__)
            decision = await stage.decide(current_agents, prompt, **kwargs)
            if not decision.candidates:
                return RoutingDecision.empty(name, stages=stage_names, short_circuited_at=type(stage).__name__)
            current_agents = [c.agent for c in decision.candidates]
            last_decision = decision

        if last_decision is None:
            return RoutingDecision.empty(name, stages=stage_names)
        return replace(last_decision, strategy=name, metadata={"stages": stage_names})


class FallbackStrategy:
    """Try strategies in order; return the first non-empty decision.

    Also falls back when a strategy raises :class:`DelegationError`.

    Parameters:
        *strategies: Strategies to try in order.
    """

    def __init__(self, *strategies: DelegationStrategy) -> None:
        self._strategies: tuple[DelegationStrategy, ...] = strategies

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Return the first non-empty downstream decision."""
        tried: list[str] = []
        for strategy in self._strategies:
            tried.append(type(strategy).__name__)
            try:
                decision = await strategy.decide(agents, prompt, **kwargs)
            except DelegationError:
                logger.warning(
                    "FallbackStrategy: %s raised DelegationError, trying next",
                    type(strategy).__name__,
                    exc_info=True,
                )
                continue
            if decision.candidates:
                return RoutingDecision(
                    candidates=decision.candidates,
                    strategy=type(self).__name__,
                    metadata={
                        "tried": tried,
                        "chosen_strategy": type(strategy).__name__,
                        "inner_metadata": dict(decision.metadata),
                    },
                )
        return RoutingDecision.empty(type(self).__name__, tried=tried)


class WeightedStrategy:
    """Parallel score blend across strategies.

    Each child strategy is run on the full agent pool. The final score
    per agent is the weighted average of per-strategy scores; agents
    absent from a strategy's candidates contribute ``0`` from that
    strategy (an explicit rejection drags down the blended score).
    Weights need not sum to ``1.0`` — they are normalised internally.

    Final candidates are filtered by ``min_score`` and ranked descending.

    .. note::
        Agents are deduped by Python object identity (``id(agent)``).
        Every child strategy must return the *same* ``FireflyAgent``
        instances that were passed in — wrapped, forked, or freshly
        constructed copies will be treated as different agents and the
        blend will silently double-count or drop contributions. The
        agent pool itself must also contain each logical agent only
        once; a pool with two references to the same object is fine,
        a pool with two distinct objects representing the same logical
        agent is not.

    Parameters:
        *weighted: ``(strategy, weight)`` pairs, one per child strategy.
        min_score: Drop candidates whose blended score is below this
            threshold (default ``0.0``).
    """

    def __init__(
        self,
        *weighted: tuple[DelegationStrategy, float],
        min_score: float = 0.0,
    ) -> None:
        self._strategies = weighted
        self._min_score = min_score

    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Run each child strategy and blend scores."""
        name = type(self).__name__
        if not agents or not self._strategies:
            return RoutingDecision.empty(name)

        total_weight = sum(w for _, w in self._strategies)
        if total_weight <= 0:
            return RoutingDecision.empty(name, error="non_positive_total_weight")

        # Keep agent identity by object id; preserve original order for ties.
        agent_order = list(agents)
        agent_ids = [id(a) for a in agent_order]
        blended: dict[int, float] = {aid: 0.0 for aid in agent_ids}
        components: dict[int, dict[str, float]] = {aid: {} for aid in agent_ids}
        strategy_names: list[str] = []

        for strategy, weight in self._strategies:
            strategy_name = type(strategy).__name__
            strategy_names.append(strategy_name)
            decision = await strategy.decide(agent_order, prompt, **kwargs)
            normalised_weight = weight / total_weight
            scored = {id(c.agent): c.score for c in decision.candidates}
            for aid in agent_ids:
                score = scored.get(aid, 0.0)
                blended[aid] += score * normalised_weight
                components[aid][strategy_name] = score

        candidates: list[Candidate] = []
        for agent, aid in zip(agent_order, agent_ids, strict=True):
            score = blended[aid]
            if score < self._min_score:
                continue
            candidates.append(
                Candidate(
                    agent=agent,
                    score=score,
                    reason="weighted blend",
                    metadata={"components": components[aid]},
                )
            )
        candidates.sort(key=lambda c: c.score, reverse=True)
        return RoutingDecision(
            candidates=tuple(candidates),
            strategy=type(self).__name__,
            metadata={
                "strategies": strategy_names,
                "min_score": self._min_score,
            },
        )


# -- Helpers -----------------------------------------------------------------


def _coerce_otel_value(value: Any) -> Any:
    """Coerce *value* to a type OpenTelemetry accepts as a span attribute.

    OTel accepts ``str``, ``int``, ``float``, ``bool``, and homogeneous
    sequences of those. Anything else is serialised to a JSON string.
    Nested containers are *not* coerced element-wise — the whole value
    falls through to ``json.dumps`` once, keeping the helper trivial.
    """
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(v, (str, int, float, bool)) for v in value):
        return list(value)
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


# -- Router ------------------------------------------------------------------


class DelegationRouter:
    """Routes prompts to agents using a pluggable :class:`DelegationStrategy`.

    Parameters:
        agents: The pool of agents available for delegation.
        strategy: The strategy used to decide among *agents*.
        memory: Optional :class:`MemoryManager` shared across all
            delegated agents. When provided, the chosen agent receives
            a forked memory scope automatically on
            :meth:`execute`/:meth:`route`.
    """

    def __init__(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        strategy: DelegationStrategy,
        *,
        memory: MemoryManager | None = None,
    ) -> None:
        self._agents = list(agents)
        self._strategy = strategy
        self._memory = memory

    @property
    def memory(self) -> MemoryManager | None:
        """The shared memory manager, if any."""
        return self._memory

    @memory.setter
    def memory(self, value: MemoryManager | None) -> None:
        self._memory = value

    async def decide(
        self,
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Run the strategy and emit the OTel decision event.

        Pure routing: does not execute the chosen agent and does not
        fork memory. Idempotent w.r.t. agent state.
        """
        start = time.perf_counter()
        decision = await self._strategy.decide(self._agents, prompt, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000.0

        top = decision.candidates[0] if decision.candidates else None
        chosen_agent_name = getattr(top.agent, "name", repr(top.agent)) if top else None
        chosen_score = top.score if top else None

        attributes: dict[str, Any] = {
            "strategy": decision.strategy,
            "candidates_count": len(decision.candidates),
            "chosen_agent": chosen_agent_name or "",
            "chosen_score": chosen_score if chosen_score is not None else -1.0,
            "duration_ms": duration_ms,
            "routing.candidates_json": json.dumps(
                [
                    {
                        "agent": getattr(c.agent, "name", repr(c.agent)),
                        "score": c.score,
                        "reason": c.reason,
                    }
                    for c in decision.candidates
                ],
                default=str,
            ),
        }
        for key, value in decision.metadata.items():
            attributes[f"routing.{key}"] = _coerce_otel_value(value)

        default_tracer.event("firefly.routing.decision", **attributes)

        logger.debug(
            "Routing decision: strategy=%s candidates=%d chosen=%s score=%s",
            decision.strategy,
            len(decision.candidates),
            chosen_agent_name,
            chosen_score,
        )
        return decision

    async def execute(
        self,
        decision: RoutingDecision,
        prompt: str | Sequence[UserContent],
        *,
        deps: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Run ``decision.chosen`` with *prompt*.

        Forks memory if the router has a :class:`MemoryManager` attached.

        Raises:
            DelegationError: If *decision* has no candidates.
        """
        agent = decision.chosen
        logger.debug("Delegated to agent '%s'", getattr(agent, "name", repr(agent)))

        if self._memory is not None and hasattr(agent, "memory"):
            agent_name = getattr(agent, "name", "delegated")
            agent.memory = self._memory.fork(working_scope_id=f"delegation:{agent_name}")

        return await agent.run(prompt, deps=deps, **kwargs)

    async def route(
        self,
        prompt: str | Sequence[UserContent],
        *,
        deps: Any = None,
        decide_kwargs: Mapping[str, Any] | None = None,
        **run_kwargs: Any,
    ) -> Any:
        """Convenience: :meth:`decide` then :meth:`execute`.

        ``**run_kwargs`` are forwarded only to the chosen agent's ``run``;
        strategy-specific kwargs go through the explicit ``decide_kwargs``
        mapping. Splitting the two avoids the previous ambiguity where the
        same kwargs were forwarded to both layers (and a kwarg the
        strategy consumed but the agent did not — or vice versa — raised
        ``TypeError`` from the wrong side).

        Existing callers using ``await router.route(prompt)`` or
        ``await router.route(prompt, deps=...)`` keep working unchanged.
        """
        decision = await self.decide(prompt, **(decide_kwargs or {}))
        return await self.execute(decision, prompt, deps=deps, **run_kwargs)
