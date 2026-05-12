# Cost Tracking Redesign

**Date:** 2026-05-12
**Status:** Design — revised after simplifier review
**Module:** `fireflyframework_agentic.observability` (cost-tracking subset)

---

## 1. Background and motivation

Today's cost-tracking subsystem (`observability/cost.py`, `observability/usage.py`, `observability/quota.py`, `agents/builtin_middleware.py::CostGuardMiddleware`) has accumulated four overlapping problems:

1. **Pricing accuracy.** A hand-curated `_DEFAULT_PRICES` dict in `cost.py` lists ~25 models with `(input, output)` rates. It ignores `cache_creation_tokens` and `cache_read_tokens` (already present on `UsageRecord`), has no concept of reasoning tokens, no batch-tier discount, and goes stale on every model release. Cross-provider aliasing (`bedrock:anthropic.*`, `azure:openai.*`) is reimplemented locally.
2. **Output flexibility.** The tracker hard-codes its two side effects — OTel metrics and structured events — inside `UsageTracker._emit_metrics` / `_emit_event`. There is no clean attachment point for users to route records to durable storage, webhooks, files, or anything else without forking the class.
3. **Budget enforcement.** Three independent paths exist: `UsageTracker._check_budget` (warning-only), `QuotaManager.check_budget_available` (daily, hard via raise), and `CostGuardMiddleware` (per-call, hard via raise). No single scoped-budget abstraction; no per-tenant or per-correlation budgets.
4. **Architecture/testability.** `UsageTracker` is a module-level singleton that owns recording, metric emission, event emission, and budget checks. Multi-tenant deployments and unit tests both pay for this coupling.

The redesign addresses all four axes in a single integrated change.

## 2. Goals and non-goals

**Goals:**

- Produce well-structured cost records and emit them to any pluggable downstream sink.
- Compute costs from the most accurate source available, with no in-repo price table to maintain.
- Provide budget enforcement at multiple scopes (global, tenant, agent, correlation, custom), with per-rule `hard` / `soft` mode.
- Keep `UsageRecord` schema unchanged so existing producers and consumers continue to work.
- Decouple recording, pricing, enforcement, and output into independently testable pieces.

**Non-goals:**

- Durable storage of cost records. The module emits to sinks; persistence is the integrator's choice (file, DB, queue, etc.).
- Rolling-window budgets (e.g. last-24h sliding). Calendar-aligned windows only in v1; rolling is additive later if needed.
- Currency support beyond USD. `genai-prices` reports USD; we store USD.
- Real-time billing reconciliation against provider invoices. Cost records are best-effort estimates (or provider-reported values when available); they are not invoices.
- Replacing the existing OTel exporter plumbing (`observability/exporters.py`). It stays as-is.

## 3. Architecture

The cost-tracking subsystem is reorganized into five small, independently-testable pieces inside `fireflyframework_agentic/observability/`:

```
observability/
├── cost/
│   ├── __init__.py          # public re-exports
│   ├── resolvers.py         # CostResolver chain (provider-reported → genai-prices)
│   └── tiers.py             # CallTier enum (STANDARD | BATCH)
├── budget.py                # BudgetGate, BudgetRule, BudgetMode, BudgetWindow, ScopeContext
├── sinks.py                 # CostSink protocol + built-ins
├── usage.py                 # UsageRecord (schema unchanged), UsageTracker (thin orchestrator)
└── quota.py                 # RateLimiter only — budget logic moved to budget.py
```

**Data flow per LLM call:**

```
LLM response (provider)
   │
   ▼
CostResolver.resolve(CostContext)  ──► first non-None strategy wins, else 0.0
   │
   ▼
UsageRecord  (cost_usd populated; schema unchanged)
   │
   ▼
BudgetGate.commit(record, scope_ctx)  ──► HARD breach raises BudgetExceededError; SOFT logs
   │
   ▼
SinkChain.emit(record)                ──► OTelMetricsSink, EventBusSink, JSONLFileSink, WebhookSink, ...
```

**Pre-call path** (used by `CostGuardMiddleware` and other gates that want to refuse before tokens are spent):

```
BudgetGate.precheck(estimated_cost_usd, scope_ctx) ──► raises early on HARD breach
```

**Multi-tenant scoping** is achieved by either (a) constructing a dedicated `UsageTracker` per tenant, or (b) passing a `ScopeContext` to `tracker.record_call(...)` so the single shared tracker's `BudgetGate` applies the right per-tenant rules. The default module-level singleton remains for single-tenant and library users.

## 4. Components

### 4.1 `cost/resolvers.py` — pricing

A cost resolver is **a list of callables tried in order**. No Protocol class, no Strategy wrapper — the contract is "callable returning `float | None`":

```python
class CallTier(StrEnum):
    STANDARD = "standard"
    BATCH    = "batch"     # 50% off on OpenAI/Anthropic batch APIs

@dataclass(frozen=True)
class CostContext:
    model: str                              # "anthropic:claude-sonnet-4-5"
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    tier: CallTier = CallTier.STANDARD
    provider_payload: Mapping[str, Any] | None = None

CostFn = Callable[[CostContext], float | None]

def provider_reported_cost(ctx: CostContext) -> float | None:
    """Return cost from the provider response when it carries a USD cost field.

    Supports OpenRouter (`usage.cost`). Returns None when no recognized field is present.
    """

def genai_prices_cost(ctx: CostContext) -> float | None:
    """Look up the model in genai-prices and multiply token-by-token.

    Honors cache_creation_tokens, cache_read_tokens, and reasoning_tokens against the
    corresponding fields of the genai-prices model record. Applies a 0.5x multiplier
    when ctx.tier == BATCH.

    On unknown model: returns None, emits `cost_unknown` counter labeled with `model`,
    and logs WARNING once per model (deduplicated process-wide).
    """

def resolve_cost(ctx: CostContext, resolvers: Sequence[CostFn] | None = None) -> float:
    """Return the first non-None result from the resolver chain, or 0.0 if all abstain."""
    chain = resolvers or DEFAULT_RESOLVERS
    for fn in chain:
        result = fn(ctx)
        if result is not None:
            return result
    return 0.0

DEFAULT_RESOLVERS: tuple[CostFn, ...] = (provider_reported_cost, genai_prices_cost)
```

Users extend the chain by passing their own list (e.g. `[my_fixed_rate, *DEFAULT_RESOLVERS]`). The `examples/cost_tracking.py` walkthrough demonstrates this for contractually-fixed-price models.

**Deleted from the codebase:**
- `observability/cost.py::_DEFAULT_PRICES`
- `observability/cost.py::StaticPriceCostCalculator`
- `observability/cost.py::GenAIPricesCostCalculator` (old shape; replaced by the new strategy class above)
- `observability/cost.py::_cross_provider_lookup` (genai-prices handles aliasing)
- `observability/cost.py::get_cost_calculator`
- Config field `cost_calculator: Literal["auto","genai_prices","static"]`

`genai-prices` is promoted from the `[costs]` optional extra to a core dependency in `pyproject.toml`.

### 4.2 `budget.py` — enforcement

```python
class BudgetMode(StrEnum):
    HARD = "hard"   # raise BudgetExceededError
    SOFT = "soft"   # log WARNING, allow the call

class BudgetWindow(StrEnum):
    LIFETIME = "lifetime"
    MONTHLY  = "monthly"    # calendar month UTC
    DAILY    = "daily"      # calendar day UTC

@dataclass(frozen=True)
class ScopeContext:
    tenant: str = ""
    agent: str = ""
    model: str = ""
    correlation_id: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_match_dict(self) -> dict[str, str]:
        """Flatten to a single string→string mapping for rule matching.

        Built-in keys ('tenant', 'agent', 'model', 'correlation_id') merge with labels;
        labels are keyed under their own names. Built-in keys win on collision.
        """

@dataclass(frozen=True)
class BudgetRule:
    name: str
    limit_usd: float
    mode: BudgetMode = BudgetMode.HARD
    window: BudgetWindow = BudgetWindow.LIFETIME
    match: Mapping[str, str] = field(default_factory=dict)
    """AND-of-key-value match against ScopeContext.to_match_dict().
    Empty dict means 'matches every call' (global rule). Example:
        match={"tenant": "acme"}           # tenant-scoped
        match={"agent": "writer"}          # agent-scoped
        match={"tenant": "acme", "env": "prod"}  # combined; 'env' read from labels
    """

class BudgetGate:
    def __init__(self, rules: Sequence[BudgetRule]): ...
    def precheck(self, estimated_cost_usd: float, ctx: ScopeContext) -> None: ...
    def commit(self, record: UsageRecord, ctx: ScopeContext) -> None: ...
    def spend(self, rule_name: str) -> float: ...
    def reset(self, rule_name: str | None = None) -> None: ...
```

**No predicate helpers.** Rules are plain data: serializable to JSON/YAML, trivially testable, debuggable in logs. Custom match logic (regex, glob, callables) is not needed for v1; if added later it would be an additive `custom_matcher: Callable | None = None` field.

**Window semantics.** Calendar-aligned, not rolling. The bucket-key helper lives in a new shared utility `observability/_windows.py`:

```python
# observability/_windows.py
def bucket_key(window: str, now: datetime) -> str:
    """Return 'lifetime', '2026-05', or '2026-05-12' depending on window."""
```

Both `BudgetGate` and `RateLimiter` (`observability/quota.py`) consume this helper so the windowing logic exists in exactly one place.

The gate stores `{rule_name: (bucket_key, accumulated_usd)}`; on each `commit`, if the current bucket key differs from the stored one, the accumulator resets to zero before adding. Lazy, lock-protected, O(1).

**`alert_at` removed.** No v1 use case; if needed later, additive change.

**Error type — extend the existing exception in place.** Do not redefine. `exceptions.py:191` already has `BudgetExceededError(QuotaError)`; we add structured fields to it:

```python
# exceptions.py — modified in place
class BudgetExceededError(QuotaError):
    """Raised when a budget rule is exceeded."""

    rule_name: str
    spend_usd: float
    limit_usd: float
    scope_ctx: "ScopeContext"

    def __init__(
        self,
        msg: str,
        *,
        rule_name: str = "",
        spend_usd: float = 0.0,
        limit_usd: float = 0.0,
        scope_ctx: "ScopeContext | None" = None,
    ) -> None: ...
```

Existing `raise BudgetExceededError("…")` call sites keep working unchanged.

**Consolidations:**
- `CostGuardMiddleware(budget_usd=...)` keeps its public constructor; internally it instantiates a `BudgetGate` with one `BudgetRule(name="costguard", limit_usd=budget_usd, mode=HARD, window=LIFETIME, scope=globally())` and wires `precheck` into the agent middleware chain.
- `QuotaManager.check_budget_available` and `QuotaManager.daily_budget_usd` are deleted; the daily-budget use case is now `BudgetRule(window=DAILY, scope=globally())`. `QuotaManager` keeps **only** rate-limiting responsibilities.
- `UsageTracker._check_budget` is deleted; the tracker calls `gate.commit(...)`.
- Config field `budget_limit_usd` is **kept** as a convenience: when set, the default tracker auto-installs a single global HARD `BudgetRule(name="config_global", limit_usd=budget_limit_usd, match={})`. The `budget_alert_threshold_usd` field is **deprecated and removed** (paired with the deleted `alert_at`); a `ConfigError` with a one-line migration pointer is raised if set, matching the treatment of the removed `cost_calculator` field.

### 4.3 `sinks.py` — output fan-out

```python
@runtime_checkable
class CostSink(Protocol):
    def emit(self, record: UsageRecord) -> None: ...
    def flush(self) -> None: ...    # default no-op
    def close(self) -> None: ...    # default no-op
```

Built-ins shipped in core:

| Sink | Purpose |
|---|---|
| `OTelMetricsSink` | Replaces today's `UsageTracker._emit_metrics`. Calls `default_metrics.record_tokens / record_prompt_tokens / record_completion_tokens / record_cost / record_latency`. Attached by default. |
| `EventBusSink` | Replaces today's `UsageTracker._emit_event`. Calls `default_events.agent_completed(...)`. Attached by default. |
| `LoggingSink(level=INFO)` | One human-readable log line per record. Off by default; opt-in for dev. |
| `JSONLFileSink(path, *, rotate_mb=None)` | One JSON line per record; optional size-based rotation; single-lock async-safe. |
| `WebhookSink(url, *, batch_size=50, flush_interval_s=5.0, headers=None)` | Background thread batches and POSTs JSON; exponential-backoff retry on 5xx; drop + `cost_sink_errors` counter on permanent failure; `close()` drains. |

**Error isolation.** Each sink's `emit()` call is wrapped in try/except inside `UsageTracker`; a failing sink does not break other sinks or the LLM call. Failures increment `cost_sink_errors{sink="ClassName"}`.

**Relationship to `observability/exporters.py`.** `exporters.py` configures the OTel SDK (TracerProvider, MeterProvider, OTLP/Azure/Console exporters); it does not know `CostSink` exists. `OTelMetricsSink` calls into the meters that `exporters.py` configured. The two files are orthogonal layers and remain so.

### 4.4 `usage.py` — orchestration

`UsageRecord` is unchanged. Every existing field stays exactly as it is today:

```
agent, model, input_tokens, output_tokens, total_tokens,
cache_creation_tokens, cache_read_tokens, request_count,
cost_usd, latency_ms, timestamp, correlation_id
```

`UsageTracker` becomes a thin orchestrator:

```python
class UsageTracker:
    def __init__(
        self,
        *,
        resolver: CostResolver | None = None,
        gate: BudgetGate | None = None,
        sinks: Sequence[CostSink] | None = None,
        max_records: int = 0,
    ) -> None: ...

    # NOTE: the legacy `record(usage)` method is removed. All call sites
    # (tests, examples) migrate to `record_call(...)`. No production code
    # in agents/reasoning/pipeline core calls it today.

    def record_call(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        reasoning_tokens: int = 0,
        tier: CallTier = CallTier.STANDARD,
        provider_payload: Mapping[str, Any] | None = None,
        agent: str = "",
        correlation_id: str = "",
        latency_ms: float = 0.0,
        scope_ctx: ScopeContext | None = None,
    ) -> UsageRecord:
        """Resolve cost → build UsageRecord → gate.commit → fan out to sinks."""

    def add_sink(self, sink: CostSink) -> None: ...
    def get_summary(self) -> UsageSummary: ...
    def get_summary_for_agent(self, name: str) -> UsageSummary: ...
    def get_summary_for_correlation(self, cid: str) -> UsageSummary: ...
    @property
    def records(self) -> list[UsageRecord]: ...
    @property
    def cumulative_cost_usd(self) -> float: ...
    def reset(self) -> None: ...
```

The module-level singleton `default_usage_tracker` is constructed with `OTelMetricsSink()` and `EventBusSink()` attached and the default resolver, preserving today's observable behavior exactly.

## 5. Example — `examples/cost_tracking.py`

A single end-to-end example demonstrates the full pipeline:

- A custom `FixedRateCost` `CostStrategy` slotted in front of the default resolver chain to demonstrate the extension point for contractually-fixed-price models.
- A `BudgetGate` with two rules: tenant-scoped HARD daily limit, and an agent-scoped SOFT lifetime limit with `alert_at=0.8`.
- A custom JSON-line sink alongside the default `OTelMetricsSink` and `EventBusSink`.
- One agent run that produces cache tokens (Anthropic prompt caching) and runs in `CallTier.BATCH`, so cache pricing, batch discount, and tenant attribution all exercise.

This example is run by CI as a smoke test.

## 6. Configuration

**Removed (raise `ConfigError` with migration pointer if set):**
- `cost_calculator: Literal["auto","genai_prices","static"]` — single resolver path now.
- `budget_alert_threshold_usd: float | None` — paired with removed `alert_at`.

**Kept:**
- `cost_tracking_enabled: bool` — when `False`, the default tracker becomes a no-op.
- `budget_limit_usd: float | None` — when set, auto-installs a global HARD `BudgetRule` on the default tracker.
- `usage_tracker_max_records: int` — unchanged.

## 7. Error handling

- **`BudgetExceededError`** is raised by `BudgetGate.precheck` and `BudgetGate.commit` on HARD rule breaches. Same exception class as today, extended with structured fields (`rule_name`, `spend_usd`, `limit_usd`, `scope_ctx`).
- **Resolver failures.** `ProviderReportedCost` swallows malformed payloads and returns `None`. `GenAIPricesCost` swallows lookup failures and returns `None`. The resolver never raises; worst case it returns `0.0`.
- **Unknown model.** Resolver returns `0.0`, `cost_unknown{model=...}` counter increments, WARNING logged once per model.
- **Sink failures.** Caught inside `UsageTracker`, never propagated. `cost_sink_errors{sink=ClassName}` counter increments. Sink `close()` is called on tracker shutdown.

## 8. Testing strategy

- **`tests/observability/test_cost_resolvers.py`** — provider-reported parsing, genai-prices token-breakdown math (cache, reasoning, batch tier), unknown-model behavior (counter + dedup), chain ordering, custom resolver injection.
- **`tests/observability/test_windows.py`** — `bucket_key` correctness for all three windows across UTC boundary crossings (parametrized). Shared utility, tested once.
- **`tests/observability/test_budget.py`** — HARD raises with populated fields, SOFT logs, overlapping rules fire independently, `match={}` rule matches every call, `match={"tenant":"acme"}` filters correctly, labels merge into match dict, lazy reset across bucket boundaries, `precheck` with `estimated_cost=0.0`.
- **`tests/observability/test_sinks.py`** — `JSONLFileSink` writes valid JSONL + rotation, `WebhookSink` batches/flushes/retries/drops + drains on close, error isolation, parity with today's metric/event emissions.
- **`tests/observability/test_usage_tracker.py`** — `record_call` end-to-end: resolver → record → gate → sinks in order; golden-record regression test on schema parity.
- **`tests/observability/test_backcompat.py`** — `CostGuardMiddleware` constructor unchanged; `budget_limit_usd` config still installs a global rule; removed `cost_calculator` and `budget_alert_threshold_usd` fields each raise `ConfigError` with migration pointer.
- **`examples/cost_tracking.py`** is run by CI as a smoke test.

All tests are plain `pytest` functions (no test classes). Test files use the `test_` prefix.

## 9. Migration and rollout

Single PR, no deprecation cycle (module is pre-1.0):

1. Add new files: `observability/cost/{__init__,resolvers,tiers}.py`, `observability/budget.py`, `observability/sinks.py`, `observability/_windows.py`, `examples/cost_tracking.py`.
2. Delete: `observability/cost.py` (whole file), `_DEFAULT_PRICES`, `StaticPriceCostCalculator`, old `GenAIPricesCostCalculator`, `_cross_provider_lookup`, `get_cost_calculator`, config fields `cost_calculator` and `budget_alert_threshold_usd`, the legacy `UsageTracker.record(usage)` method.
3. Modify: `observability/usage.py` (thin orchestrator + new `record_call`; legacy `record` removed), `observability/quota.py` (drop budget code; `RateLimiter` consumes `_windows.bucket_key`), `agents/builtin_middleware.py::CostGuardMiddleware` (delegate to `BudgetGate`), `exceptions.py::BudgetExceededError` (extend in place with structured fields and `__init__` accepting them as kwargs).
4. Migrate existing call sites in tests and examples from `tracker.record(usage)` to `tracker.record_call(...)`. Affected files: `examples/observability_usage.py`, `tests/unit/observability/test_usage.py`, `tests/unit/pipeline/test_pipeline_usage.py`.
5. `pyproject.toml`: move `genai-prices` from `[costs]` extra to core dependencies; remove the `[costs]` extra.
6. Docs: rewrite the "Cost Calculation" section of `docs/observability.md`; add new "Budgets" and "Cost Sinks" sections.
7. `CHANGELOG.md`: **Breaking changes** entry listing the removed config fields, removed classes, and removed `record(usage)` method.

## 10. Open questions

None at design time. Implementation may surface minor questions about `genai-prices` field names for reasoning / cache tokens; the implementation plan will resolve them against the installed library version.

## 11. Revision history

**2026-05-12 — Simplifier review pass.** Changes from the initial design after running parallel reuse / over-engineering / deletion reviewers:

- `CostResolver` collapsed from Protocol + class to `list[CostFn]` + module-level `resolve_cost()`. Two free functions (`provider_reported_cost`, `genai_prices_cost`) replace the strategy classes.
- `BudgetRule.scope: Callable[[ScopeContext], bool]` replaced with `match: dict[str, str]` (AND-of-key-value). Helpers `by_tenant` / `by_agent` / `globally` deleted; rules are now serializable plain data.
- `BudgetWindow` trimmed from five values to three (`LIFETIME`, `MONTHLY`, `DAILY`). YEARLY and HOURLY removed pending real demand.
- `alert_at` removed from `BudgetRule`; config field `budget_alert_threshold_usd` removed in tandem.
- `BudgetExceededError` extended **in place** in `exceptions.py:191` rather than redefined.
- `bucket_key` window utility extracted to `observability/_windows.py` and shared with `RateLimiter`.
- `WebhookSink` **kept in core** (user decision; overrides reviewer recommendation to move to example).
- Legacy `UsageTracker.record(usage)` method removed; test/example call sites migrate to `record_call(...)`.
- `ScopeContext` kept separate from `agents/context.py::AgentContext` (different concerns: filter shape vs. runtime carrier); the call site populates one from the other.
