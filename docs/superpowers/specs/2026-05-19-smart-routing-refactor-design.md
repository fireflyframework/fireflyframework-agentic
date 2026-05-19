# Smart Routing Refactor — Design

**Issue:** [fireflyframework-agentic#149](https://github.com/fireflyframework/fireflyframework-agentic/issues/149).
**Date:** 2026-05-19.
**Module:** `fireflyframework_agentic.agents.delegation`.

## Problem

The current `DelegationStrategy` contract (`fireflyframework_agentic/agents/delegation.py`) has four limitations that block real use cases:

1. **Rigid return shape.** `select() -> FireflyAgent` returns exactly one agent. No room for ranked candidates, scores, rationale, or "no opinion" responses. Top-k, probabilistic routing, and ensemble decisions are impossible without subclassing the router.
2. **No composition.** Combining "capability AND cost-aware" or "content-based with round-robin fallback" requires writing a new strategy class. There is no way to reuse the four built-ins as building blocks.
3. **No observability.** Decisions surface only through `logger.debug`. There is no structured trace of why an agent was picked, no metrics, no audit trail.
4. **Selection coupled to execution.** `DelegationRouter.route()` does select + run in one method. Callers cannot inspect or override the decision, dry-run a strategy, cache decisions, or retry execution with the next-best candidate.

Two existing strategies also have honesty problems: `CapabilityStrategy` raises on no-match (preventing composition with fallback), and `ContentBasedStrategy` silently returns the first agent on LLM failure (hiding errors).

A related concern: `CostAwareStrategy` carries a hardcoded model→tier table that drifts out of date. The project already has a canonical pricing source (`fireflyframework_agentic.observability.cost_resolvers.resolve_cost`, backed by `genai-prices`); the routing refactor is the natural moment to switch.

## Goals

- Allow strategies to return ranked, scored, multi-candidate decisions.
- Allow strategies to compose via sequential narrowing, fallback, and weighted blending.
- Emit one structured decision event per routing call, integrated with the existing OTel hook.
- Split selection from execution so decisions are plain data that can be inspected, cached, dry-run, or replayed.
- Replace `CostAwareStrategy`'s hardcoded tier table with the existing cost resolver chain.
- Keep `DelegationRouter.route()` as a one-call convenience so existing user code is unaffected.

## Non-Goals

- Per-request model routing (one agent, multiple models). Out of scope; tracked separately if it becomes a real need.
- A built-in `execute_with_fallback` cascade helper. Retry-on-failure stays the caller's responsibility for now; ship the helper when a real use case appears.
- New metrics beyond the OTel routing event. Anything else can be derived from the event.

## Core Types

```python
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable
from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.types import UserContent

@dataclass(frozen=True)
class Candidate:
    agent: FireflyAgent[Any, Any]
    score: float          # in [0.0, 1.0], higher = better
    reason: str           # short human-readable explanation

@dataclass(frozen=True)
class RoutingDecision:
    candidates: tuple[Candidate, ...]   # ranked best-first; may be empty
    strategy: str                       # producing strategy class name
    metadata: Mapping[str, Any]         # free-form; flattened into the OTel event

    @property
    def chosen(self) -> FireflyAgent[Any, Any]:
        if not self.candidates:
            raise DelegationError("Empty routing decision")
        return self.candidates[0].agent

@runtime_checkable
class DelegationStrategy(Protocol):
    async def decide(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision: ...
```

### Score conventions

Scores are normalised to `[0.0, 1.0]`, higher is better. Per-strategy conventions:

- **Binary match** (e.g. `CapabilityStrategy`): `1.0` on match, omit candidate on no-match.
- **Tier or numeric scale** (e.g. `CostAwareStrategy`): pool-relative linear normalisation, `score = 1.0 - (cost - min) / (max - min)`, ties resolve to `1.0`.
- **LLM-judged** (e.g. `ContentBasedStrategy`): use LLM-supplied confidence when available, else `1.0 / rank`.
- **No opinion on quality** (e.g. `RoundRobinStrategy`): always `1.0`; turn-order info goes in `metadata`.

Empty `candidates` tuple is a meaningful signal — it means "this strategy has no opinion" and is what enables `FallbackStrategy`. The router only raises if the *final* decision (after combinators) is empty and `execute()` is called.

## Combinators

All three combinators implement `DelegationStrategy` themselves, so they nest freely.

### `ChainStrategy`

Sequential narrowing. Each stage receives the *surviving candidate agents* from the previous stage (not the full pool). Final stage's scores are returned. Empty intermediate decision short-circuits to an empty result.

```python
class ChainStrategy:
    def __init__(self, *stages: DelegationStrategy) -> None: ...
```

Typical use: `ChainStrategy(CapabilityStrategy("vision"), CostAwareStrategy())` — first keep vision-capable agents, then rank the survivors by cost.

### `FallbackStrategy`

Try strategies in order, return the first non-empty decision. Also falls back on `DelegationError` raised inside a strategy.

```python
class FallbackStrategy:
    def __init__(self, *strategies: DelegationStrategy) -> None: ...
```

Typical use: `FallbackStrategy(ContentBasedStrategy(), RoundRobinStrategy())` — try the LLM router, default to round-robin if it returns nothing.

### `WeightedStrategy`

Parallel score blend. Each child strategy is run on the full agent pool; final score per agent is the weighted average. Weights need not sum to 1.0 — they are normalised internally (`weight_i / sum(weights)`). Agents absent from a strategy's candidates contribute 0 *from that strategy* (an explicit rejection drags down the blended score). Final candidates are filtered by `min_score` and ranked descending.

```python
class WeightedStrategy:
    def __init__(
        self,
        *,
        strategies: Sequence[tuple[DelegationStrategy, float]],
        min_score: float = 0.0,
    ) -> None: ...
```

Typical use: `WeightedStrategy(strategies=[(CapabilityStrategy("vision"), 3), (CostAwareStrategy(), 1)])` — capability matters three times as much as cost, but neither vetoes the other.

## `DelegationRouter` API

```python
class DelegationRouter:
    def __init__(
        self,
        agents: Sequence[FireflyAgent[Any, Any]],
        strategy: DelegationStrategy,
        *,
        memory: MemoryManager | None = None,
    ) -> None: ...

    async def decide(
        self,
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Pure routing. Runs the strategy, emits a decision event,
        returns. Does not execute the agent. Idempotent w.r.t. agent state."""

    async def execute(
        self,
        decision: RoutingDecision,
        prompt: str | Sequence[UserContent],
        *,
        deps: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Run decision.chosen with prompt. Forks memory if attached.
        Raises DelegationError on empty decision."""

    async def route(
        self,
        prompt: str | Sequence[UserContent],
        **kwargs: Any,
    ) -> Any:
        """Convenience: decide(prompt) then execute(...). Existing callers
        keep working unchanged."""
```

Three design notes:

- `execute()` takes both the decision and the prompt. Decisions are plain data, not closures over a prompt, so they can be cached, dry-run, A/B compared, or serialised for audit.
- Retry-with-next-candidate is the caller's responsibility. Callers that want it iterate `decision.candidates` themselves; building it into the router would force opinions on idempotency, deps, and timeouts.
- `route()` signature is exactly today's. The only public-API addition users *must* care about is the strategy protocol change.

## Migration of Built-In Strategies

All four current strategies port to `decide()` mechanically.

### `RoundRobinStrategy`

Returns a 1-element decision, `score=1.0`, `reason="round-robin turn"`, `metadata={"turn": n}`. Empty pool → empty decision (no exception; the protocol pushes that to the router boundary).

### `CapabilityStrategy`

Returns *all* matching agents (today returns only the first), `score=1.0` for each, `reason="has tag '<tag>'"`. Non-matching agents are omitted. **Behavioural change:** no-match now returns an empty decision rather than raising `DelegationError`. This is what makes capability composable with `FallbackStrategy`.

### `ContentBasedStrategy`

Returns ranked candidates when the LLM produces a ranking, otherwise a 1-element decision. Score from LLM confidence if available, else `1.0 / rank`. **Behavioural change:** LLM failure now returns an empty decision (so `FallbackStrategy` can take over) rather than silently returning the first agent.

### `CostAwareStrategy`

Hardcoded `_COST_TIERS` table is removed. Cost per agent is computed by calling `resolve_cost` from `fireflyframework_agentic.observability.cost_resolvers` with a representative synthetic `CostContext`.

```python
class CostAwareStrategy:
    def __init__(
        self,
        *,
        sample_input_tokens: int = 1000,
        sample_output_tokens: int = 500,
        sample_cache_creation_tokens: int = 0,
        sample_cache_read_tokens: int = 0,
        sample_reasoning_tokens: int = 0,
        resolvers: Sequence[CostFn] | None = None,
        on_unknown: Literal["skip", "lowest", "raise"] = "skip",
    ) -> None: ...
```

Scoring: pool-relative linear normalisation. For each agent, compute USD via `resolve_cost(CostContext(model=agent.model_name, ...), resolvers=resolvers)`. Then `score = 1.0 - (cost - min) / (max - min)` over the priced set; all-equal costs → all `1.0`; single agent → `1.0`. `on_unknown` controls handling for models the resolver chain cannot price:

- `"skip"` (default) — omit the agent from the decision.
- `"lowest"` — include with `score=0.0`.
- `"raise"` — raise `UnknownModelCostError` (matches the resolver's `strict=True` semantics).

Representative tokens are required because `genai-prices` returns 0 for 0 tokens (every model would tie). Synthetic defaults (1000 in / 500 out) give stable relative ordering reflecting actual rate structure, including cache and reasoning token rates the resolver already models.

Pool-relative is a deliberate choice: the strategy answers "cheapest *of these*", which is the routing question. Same agent pair can score differently in different pools — that is the correct semantics, not a bug.

## Observability

One structured event per `decide()` call, emitted via the existing OTel hook (see `docs/observability.md`). Top-level router emits; combinators do not — sub-strategy detail lives in `metadata`.

```
event: firefly.routing.decision
attributes:
  strategy: str                # top-level strategy class name
  candidates_count: int
  chosen_agent: str | None     # name of candidates[0].agent, or None if empty
  chosen_score: float | None
  duration_ms: float
  routing.<key>: <value>       # decision.metadata, flattened with `routing.` prefix
```

Per-candidate ranking (agents, scores, reasons) goes into a span attribute as a single JSON string to keep cardinality bounded. No new metrics in this refactor — `routing_decisions_total{strategy=...}`, fallback-rate, etc. can be derived later from events if needed.

## Back-Compat

Two breaking changes, documented in `CHANGELOG.md` under a `BREAKING` heading.

1. **`DelegationStrategy` protocol** — `select() -> Agent` replaced by `decide() -> RoutingDecision`. No deprecation shim: the protocol is small, in-tree implementations are 4, and a shim would lock in the single-agent return shape we are explicitly escaping. External implementers get a clean `Protocol` mismatch at type-check time.
2. **Empty-decision semantics for `CapabilityStrategy` and `ContentBasedStrategy`.** Both previously raised / silently fell back; both now return empty decisions. Callers using bare `router.route()` still see `DelegationError("Empty routing decision")` from `execute()` — same exception class, different message.

`DelegationRouter.route()` keeps its exact current signature and return type, so the common call site is unaffected.

## Testing

New tests cover:

- `RoutingDecision.chosen` raises on empty, preserves order.
- Each migrated strategy on: empty pool, single agent, ranking correctness, score range `[0,1]`.
- `CostAwareStrategy`: pool-relative normalisation correctness; all `on_unknown` modes; resolver chain override.
- `ChainStrategy`: narrowing across stages, short-circuit on empty intermediate.
- `FallbackStrategy`: skips empty decisions, skips on `DelegationError`, returns first non-empty.
- `WeightedStrategy`: weights normalised internally, absent agents contribute 0, `min_score` filter, score stays in `[0,1]`.
- `DelegationRouter.decide()` is pure (no agent execution, no memory fork). `execute()` forks memory, raises on empty decision.
- OTel event emitted once per `decide()`, with expected attributes.

Existing delegation tests stay green via `route()`.

## File Layout

Changes are confined to:

- `fireflyframework_agentic/agents/delegation.py` — types, protocol, four migrated strategies, three combinators, router API.
- `fireflyframework_agentic/agents/__init__.py` — re-export `Candidate`, `RoutingDecision`, `ChainStrategy`, `FallbackStrategy`, `WeightedStrategy`.
- `tests/agents/test_delegation.py` — new and updated tests.
- `docs/architecture.md` and `docs/agents.md` — class diagram and prose updated to reflect new types.
- `CHANGELOG.md` — BREAKING entries.
