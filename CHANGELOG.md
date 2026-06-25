# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

## [26.06.13] - 2026-06-22

Best-in-class auto-instrumentation, on by default — plus an observability-metrics de-dup.

### Changed (behavioural)

- **Native pydantic-ai instrumentation is now ON by default** (`native_instrumentation_enabled`
  defaults to `True`, gated by `observability_enabled`). Every agent emits rich
  GenAI-convention spans + metrics for each model request (`chat`) and tool call
  (`execute_tool`), nested under the framework's `agent.{name}` span. Default-on is
  safe because the framework leaves the tracer/meter providers unset (telemetry flows
  through the global OTel API and costs nothing until the host wires an exporter) and
  **prompt/response content is stripped by default** (`instrumentation_include_content=False`).
  Set `native_instrumentation_enabled=false` to opt out (e.g. to cut span volume on
  very high-throughput hosts).
- **Single source of truth for metrics.** `ObservabilityMiddleware` no longer emits
  `firefly.tokens.total` / `firefly.latency` — these (and `firefly.cost.total`, the
  prompt/completion token split) are emitted solely by the usage/cost-sink path
  (`UsageTracker` → `OTelMetricsSink`), which previously **double-counted** them in
  every metrics backend. The middleware now owns only the span lifecycle (matching the
  existing `agent.completed` de-dup). Metrics flow when `cost_tracking_enabled` (default
  `True`). The span also now carries `firefly.correlation_id`.

### Fixed

- Removed a stale `# RubricReviewer (placeholder — full implementation in subsequent
  tasks)` comment — `RubricReviewer` is fully implemented and tested; the comment was
  misleading.

## [26.06.12] - 2026-06-22

SP-10: native pydantic-ai OpenTelemetry instrumentation.

### Added

- **Native instrumentation** for FireflyAgents via pydantic-ai's
  `capabilities=[Instrumentation(InstrumentationSettings(...))]` — rich
  GenAI-semantic-convention spans for **each model request** (`chat <model>`) and
  **each tool call** (`execute_tool <name>`), with provider, model, and token
  usage. Off by default; enable with `native_instrumentation_enabled`. Four config
  fields (env `FIREFLY_AGENTIC_*`):
  - `native_instrumentation_enabled` (`False`) — master switch; effective only when
    `observability_enabled` is also `True`.
  - `instrumentation_include_content` (`False`) — privacy-safe default; prompt/response
    text and tool args/results are stripped from spans unless opted in (overrides
    pydantic-ai's own `include_content=True`).
  - `instrumentation_version` (`2`) — GenAI convention version (`1`–`5`).
  - `instrumentation_event_mode` (`attributes`) — span attributes vs OTel logs.
  Uses the **non-deprecated** capabilities API (never `Agent(instrument=)`, which
  emits a `PydanticAIDeprecationWarning` the SP-9 gate would reject). Providers left
  unset → spans flow through the global OTel API; the host owns the SDK/exporter.

### Changed

- `ObservabilityMiddleware` now **activates** its `agent.{name}` span in the OTel
  context (attach in `before_run`, detach in `after_run` and `on_error`) so spans
  created during the run — notably the native instrumentation spans — **nest under**
  it instead of becoming disjoint roots in a separate trace. The span also carries
  `firefly.correlation_id` (the join key to cost records). The detach runs on every
  exit path (success, error, streaming, HITL pause) with no context-token leak.

### Notes

- Two complementary altitudes per run: the coarse firefly `agent.{name}` envelope
  (name/method/correlation_id) and the fine native `invoke_agent → chat / execute_tool`
  tree (`gen_ai.*`). No duplicate model span — pydantic-ai de-dups internally.
- Verified with an in-memory OTel exporter (nesting, gating, privacy, no deprecation
  warning, one chat span per request) and live against Anthropic (real
  `claude-haiku-4-5` spans with real token usage, nested, content stripped).
- This closes the deferred SP-10: the memory's "blocked on pydantic-ai 2.0 capabilities
  surface" was outdated — the `Instrumentation` capability is available and warning-free
  on the pinned 1.x line.

## [26.06.11] - 2026-06-22

SP-3: human-in-the-loop tool approval re-based onto pydantic-ai native deferred-tools.

### Added

- **Native tool approval / HITL.** Tools can declare `requires_approval=True`
  (`firefly_tool(...)`, `BaseTool`, and threaded through `ToolKit.as_pydantic_tools()`
  / `as_toolset()`). When the model calls such a tool, the agent run **pauses before
  executing it** and returns a `DeferredToolRequests` as `result.output`. Detect with
  the new `is_deferred(result)` helper; **resume** via
  `agent.run(message_history=..., deferred_tool_results=DeferredToolResults(approvals={call_id: True | ToolApproved(override_args=...) | ToolDenied(message=...)}))`.
  `FireflyAgent` auto-detects HITL (any approval-requiring tool/`ToolKit`/`as_toolset()`,
  or an `ApprovalRequiredToolset` in `toolsets`) and widens its output union to allow the
  pause **only then** — non-HITL agents are unchanged. Force with `hitl=True`.
- **Inline (non-pausing) approval.** `FireflyAgent(approval_handler=...)` resolves
  approvals *inside* the run via a native `HandleDeferredToolCalls` capability — for
  programmatic / policy-based auto-approval.
- **Native re-exports** from `fireflyframework_agentic.tools`: `DeferredToolRequests`,
  `DeferredToolResults`, `ToolApproved`, `ToolDenied`, `ApprovalRequired` (plus the
  already-exported `ApprovalRequiredToolset`). `is_deferred` and the `ApprovalHandler`
  type are exported from `fireflyframework_agentic.agents`.

### Changed

- Post-run cross-cutting code now treats a paused run as a control object, not a final
  answer: `_persist_memory`, the output-guard, validation, cache, logging, and
  explainability middleware all **skip** a `DeferredToolRequests` output (preventing
  corrupted memory turns, spurious `OutputGuardError`/`OutputReviewError`, and caching a
  pause).
- Tool **guard denials** (validation / rate-limit / sandbox) now raise `ToolGuardError`
  instead of a plain `ToolError`. `ToolGuardError` subclasses `ToolError`, so existing
  `except ToolError` handlers are unaffected.
- `BaseTool._guarded_execute` now lets pydantic-ai's `ApprovalRequired` / `CallDeferred`
  control signals propagate untouched (like `ModelRetry`), instead of wrapping them as
  `ToolError`. This makes **dynamic** approval work — a tool body (with `takes_ctx=True`)
  may `raise ApprovalRequired(metadata=...)` to defer that specific call; pair with
  `FireflyAgent(hitl=True)` so the output union allows the pause.

### Removed (breaking)

- **`ApprovalGuard`** (and the `ApprovalCallback` alias). The bespoke guard-chain approval
  (sync bool callback → `ToolError` on denial, no pause/resume/metadata) is replaced by the
  native protocol above. Migration: `docs/migration.md` §6.

### Notes

- HITL stays three distinct layers by design: tool approval (native deferred-tools, agent
  layer), workflow `human()` / `WorkflowInterrupt` (journal-replay), and pipeline `Pause`
  / `approve_pause` (checkpoint). They are not collapsed.
- Validated against a live Anthropic model: a `requires_approval` tool pauses the real run
  (tool body does not execute), and resuming with approval runs it exactly once.

## [26.06.10] - 2026-06-22

SP-5: native structured-output modes for reasoning patterns.

### Added

- **Selectable output modes on the real-model reasoning paths.** Reasoning's
  structured calls (`_structured_run`) now wrap the `output_type` in a pydantic-ai
  output mode chosen via a new per-pattern `output_mode=` argument or the
  framework-wide `reasoning_output_mode` config value
  (`FIREFLY_AGENTIC_REASONING_OUTPUT_MODE`):
  - `None` (default) — pydantic-ai's default tool-calling output (no behaviour change).
  - `"tool"` — force tool-based structured output (`ToolOutput`).
  - `"native"` — provider-native JSON-schema output (`NativeOutput`; OpenAI/Google/…).
  - `"prompted"` — schema-in-prompt JSON parsing (`PromptedOutput`); the portable
    choice for models without tool-calling or native structured output.
  Threaded through all six concrete patterns (ReAct, Chain-of-Thought,
  Plan-and-Execute, Tree-of-Thoughts, Reflexion, Goal-Decomposition). New
  `OutputMode` type alias exported from `fireflyframework_agentic.reasoning`.
  Resolution order: per-pattern argument → config default → pydantic-ai default.

### Notes

- The model-less duck-typed fallback (`_fallback_parse`, used by mocks/agents
  without a resolvable model) is unchanged — it cannot make an LLM call, so it
  keeps its text-parsing graceful-degradation cascade. Output modes apply only
  to the two real-model paths (FireflyAgent route + ephemeral agent).
- Validated against a live Anthropic model: a Chain-of-Thought pattern with
  `output_mode="prompted"` produces correct validated structured steps end to end.

## [26.06.9] - 2026-06-22

Documentation coverage pass — every 26.06.x change is now explained, with two new
reference guides and several corrected docs (driven by a per-doc audit verified
against the source).

### Added

- **`docs/resilience.md`** — the circuit breaker (state machine, direct
  `async with CircuitBreaker(...)` usage, `CircuitBreakerMiddleware` agent wiring,
  inspection/reset, API reference).
- **`docs/storage.md`** — the managed-SQLite durable layer (`StorageBackend`,
  `LocalBackend`, `DatabaseStore`, `WriteSession`/`LockToken` leasing, atomic writes,
  the `SqliteVecVectorStore` consumer, types/exceptions reference).
- **Multi-Provider Support** section in `docs/architecture.md` consolidating the
  "works with any provider" story (identity normalisation, provider-aware cost,
  prompt-cache routing, tool-schema portability, failover/rate-limit handling).

### Changed (docs)

- `agents.md`: documented the middleware **error lifecycle** (`on_error` / LIFO
  `run_error`), the `ObservabilityMiddleware` span-on-error and `CircuitBreaker`
  failure-recording-via-`on_error`, `MiddlewareContext` fields, and
  `model_settings`/`default_temperature` (provider-safe `None` default). Fixed a
  **factual error**: corrected the OpenAI prompt-cache mechanism and documented that
  Claude via Bedrock/OpenRouter is skipped with a warning.
- `reasoning.md`: documented that structured runs route through the source
  `FireflyAgent` (middleware/retry/usage) rather than a bare `pydantic_ai.Agent`.
- `observability.md`: provider-agnostic identity → cost, provider-aware reasoning
  tokens (Gemini `thoughts_tokens`), the strict-mode/Budget-priceable-only caveat,
  and the Bedrock vendor-prefix retry; fixed the misleading reasoning-token claim.
- `tools.md`: corrected `retryable` (wraps `_execute`), documented `CachedTool`
  single-flight, the `FallbackComposer` chained traceback, and the Gemini
  free-form-schema constraint.
- `workflows.md`: `stream()` structured-output fallback, the precise `using=`
  rejection/forwarding behaviour, and `cascade()` `output_type`/`instructions`/
  `max_escalations`. `tutorial.md`: corrected the stale `default_temperature` default.
- docs index + README Module Reference now list **Resilience** and **Storage**.

### Fixed

- The middleware **error lifecycle is now uniform**: `run_with_reasoning()` also
  fires `on_error` on failure (previously only `run`/`run_sync`/`run_stream` did), so
  circuit breakers and span cleanup work for reasoning runs too.

## [26.06.8] - 2026-06-22

Provider-aware reasoning-token cost accounting (COST-001/COST-002) — the last
open audit item.

### Fixed

- **Gemini thinking tokens are now priced.** Gemini reports thinking under
  `usage.details["thoughts_tokens"]` and *excludes* them from `output_tokens`, so
  they were previously uncounted (a ~4× undercount for thinking-heavy calls). The
  agent, reasoning and workflow cost paths now fold them in at the output rate via
  a shared `reasoning_tokens_not_in_output(usage)` helper.
- **No double-counting on OpenAI/Anthropic.** The helper reads the Gemini-specific
  `thoughts_tokens` key only — OpenAI's `reasoning_tokens` are already inside
  `output_tokens` (reading them would inflate o-series cost ~53%) and Anthropic
  folds thinking into `output_tokens` too, so both contribute `0`. Corrected the
  stale resolver docstrings that implied otherwise.

### Changed

- **`genai-prices` pinned to `>=0.0.66,<0.1`.** It is a pre-1.0 package whose
  `Usage`/`calc_price` surface could change between minors and break all cost
  resolution at once; bumps are now deliberate.
- `provider_reported_cost` (OpenRouter authoritative per-call USD) documented as a
  seam for custom integrations — pydantic-ai 1.107 does not surface that cost on
  the result/usage, so it is populated only when a caller passes `provider_payload`.

## [26.06.7] - 2026-06-21

The deferred P2/P3 wave from the framework audit — provider robustness, durability,
thread-safety and observability of failures.

### Fixed

- **Cache stampede** — `CachedTool` now **single-flights** concurrent identical
  misses (the first caller computes; the rest await the same result), and uses an
  `asyncio.Lock`, so an expensive/rate-limited tool runs once per key.
- **Atomic durable writes** — `FileCheckpointer` (pipeline) and `FileJournalBackend`
  (workflows) write to a temp file and `os.replace`, so a crash mid-write can't leave
  a truncated checkpoint / resume journal.
- **Delegation thread-safety** — `RoundRobinStrategy` (cursor) and
  `ContentBasedStrategy` (lazy router build) are guarded by locks; concurrent routing
  no longer races the cursor or constructs duplicate routers.
- **Prompt-cache no longer silently no-ops on Bedrock/OpenRouter** — Claude via those
  providers logs a warning and skips (the Anthropic cache settings only apply to the
  direct `AnthropicModel`) instead of writing dead settings.
- **Bedrock cost resolution** — on a genai-prices miss for a `bedrock:vendor.model`
  id, retry on the bare model name with the vendor as the provider before giving up.
- **Provider retry hints** — the rate-limit backoff prefers a provider's *structured*
  retry hint (e.g. Gemini `ResourceExhausted.retry_delay`) before the
  OpenAI/Anthropic-shaped textual body.
- **`RetryMiddleware.backoff_multiplier`** is now honoured (it was dead config — the
  override path never passed it to `AdaptiveBackoff`).
- **Gemini-safe tool schema** — the built-in `DatabaseTool` `params` argument is now a
  JSON-object *string* instead of a free-form `dict[str, Any]` (whose open object
  schema Gemini's `FunctionDeclaration` rejects); a dict is still accepted from
  non-LLM callers.
- **Error context preserved** — `FallbackComposer` and `run_with_fallback` keep the
  original traceback (`raise … from …`) instead of discarding it on exhaustion.
- Usage-recording failures now log at **warning** (not debug), so a silently-broken
  cost/budget pipeline is visible.

### Changed

- `QuotaManager` exposes a public `backoff` property; framework internals no longer
  reach into the private `_backoff`.

### Deferred (documented)

- COST-001/COST-002 (provider-aware reasoning-token pricing + `provider_payload`
  plumbing) remain open: a naive caller-side reasoning-token add would double-count
  OpenAI (whose `output_tokens` already includes them), so the correct fix needs
  provider-aware normalisation and is tracked separately.

## [26.06.6] - 2026-06-21

Provider-agnosticism, cross-subsystem cohesion and correctness hardening, driven
by a framework-wide audit (6 lenses, adversarially verified) and validated against
a **live Anthropic model** end to end. All nine confirmed P0/P1 findings addressed.

### Fixed

- **Provider identity for `Model` objects** — `model_utils.extract_model_info` now
  reads the provider from the model's own `_provider.name`, so `OpenAIResponsesModel`,
  `GoogleModel`, `XaiModel`, `OpenRouterModel`, Azure/DeepSeek, etc. resolve to the
  correct `provider:model` instead of dropping the provider (which corrupted cost
  lookup, quota keys and usage grouping for any non-string model).
- **Model-family detection** — match on the model *name* only, fixing
  `ollama:…`/`groq:…` being misclassified as `meta` (the substring `llama` lived
  inside `ollama`); added `grok`→`xai`; multi-vendor proxies fall back to `unknown`.
- **Structured-output streaming no longer crashes** — `StreamHandle.text()` falls
  back to stringified `stream_output()` snapshots and `stream_tokens()` raises a
  clear `AgentError` when a run is non-text, instead of an opaque pydantic-ai
  `UserError`.
- **Middleware error lifecycle** — added an `on_error` hook to the middleware
  protocol/chain and wired it into `run`/`run_sync`/`run_stream`. The
  `CircuitBreakerMiddleware` can now actually open, and `ObservabilityMiddleware`
  ends its OTel span on a failed run instead of leaking it.
- **Reasoning runs through `FireflyAgent`** — a reasoning pattern's structured
  calls now route through the source `FireflyAgent` (middleware, 429 retry, usage
  recording) when available, instead of a bare ephemeral `pydantic_ai.Agent`; the
  recorded model identifier is normalised (no more `str(Model)` reprs in cost).
- **`cost_strict` is honoured on every path** — the workflow `price_call` and the
  agent usage path no longer swallow `UnknownModelCostError`, so an unpriceable
  model fails closed under `cost_strict` instead of being billed as `$0`.
- **`retryable()` applies where it matters** — wraps the `_execute` hook, so
  retries now cover the pydantic-ai handler path and `RunContext`-aware tools (not
  just a direct `tool.execute()` call).

### Changed

- **`default_temperature` is wired and provider-safe** — now defaults to `None`
  (use the provider's own default) and is merged into an agent's model settings
  only when configured and the caller omits it; previously the knob was silently
  ignored. This avoids forcing a temperature on models that reject one (e.g. OpenAI
  `o1`/`o3`).
- `config.budget_limit_usd` docstring corrected (it raises `BudgetExceededError`,
  not "logs a warning") and documents that the gate enforces only over priceable
  models.

### Added

- **Live end-to-end test suite** (`tests/integration/test_real_anthropic_e2e.py`,
  `@pytest.mark.nightly`, skipped without a real `ANTHROPIC_API_KEY`) covering the
  whole stack against a real Anthropic model: agent + tools, structured output,
  streaming, multi-turn memory, a reasoning pattern, a pipeline, a Dynamic Workflow
  (`FireflyAgentRunner` + `using=`) and cost tracking. Closes the previous gap where
  every provider-facing behaviour was validated only against mocks; `tests/README.md`
  corrected to match.

## [26.06.5] - 2026-06-21

Framework alignment: the Dynamic Workflows engine and the tools system now run on
the framework's own primitives and on pydantic-ai's native model — no parallel
implementations, no lossy shims. Includes breaking changes; see the
[Migration Guide](https://github.com/fireflyframework/fireflyframework-agentic/blob/main/docs/migration.md).

### Changed (BREAKING)

- **Tool parameters use a real `python_type`.** `ParameterSpec` and
  `ToolBuilder.parameter(name, python_type, …)` now take a real Python type object
  (`list[str]`, `Literal[...]`, a nested `BaseModel`, `dict[str, Any] | None`, …)
  instead of a string `type_annotation`. pydantic-ai introspects it directly, so the
  LLM gets full-fidelity schemas (element types, enums and nested models are
  preserved). The string `type_annotation` field and its resolver (`_TYPE_MAP`,
  `_resolve_param_type`) are **removed**; all built-in tools were migrated.
- **`FireflyAgentRunner` is the default workflow runner.** Workflow sub-agents now
  run through a `FireflyAgent` (middleware, observability, guards, 429-retry, global
  usage tracker / budget gate, model fallback) instead of a bare `pydantic_ai.Agent`.
  Global cost tracking and a configured `budget_limit_usd` now apply to sub-agents.
  The model-resolution contract is unchanged; pass `runner=DefaultAgentRunner()` for
  the previous lightweight path.

### Added

- **`FireflyAgentRunner`** — runs each workflow call through a `FireflyAgent`; its
  source may be `None` (a fresh isolated ephemeral agent per call), a `FireflyAgent`
  instance (reused), a registry name, or a factory. Tokens/cost are booked once per
  ledger (per-run `WorkflowBudget` and the global tracker, disjoint).
- **`agent(..., using=<FireflyAgent | name>)`** (and `stream(..., using=)`) — target a
  specific configured agent for one call: multi-model sub-agents and per-task cost
  optimisation. Composes with `SmartRoutingRunner`.
- **Tool `RunContext` opt-in** — `BaseTool(..., takes_ctx=True)` delivers pydantic-ai's
  `RunContext` (agent deps, usage, retries) to `_execute` as the keyword-only `_ctx`;
  guards and the cache never see it, so it cannot poison a cache key.
- **Native toolset combinators re-exported** from `fireflyframework_agentic.tools`:
  `RunContext`, `FilteredToolset`, `PrefixedToolset`, `RenamedToolset`,
  `CombinedToolset`, `WrapperToolset`, `PreparedToolset`, `ApprovalRequiredToolset`,
  plus the `to_pydantic_handler(tool)` helper.
- **Migration guide** (`docs/migration.md`).

### Fixed

- `ToolKit.as_toolset()` now forwards each tool's **description** to the model
  (pydantic-ai's `add_function` dropped it before), so toolset tools are no longer
  description-less to the LLM.

## [26.06.4] - 2026-06-21

Dynamic Workflows — the final SOTA wave: token-level streaming and end-to-end
static typing of the DSL.

### Added

- **Streaming** — `stream(prompt, ...)` is an async context manager that streams one
  sub-agent's output token-by-token: iterate `handle.text()` for deltas, then read
  `handle.output` for the full result after the block. It honours the budget,
  concurrency gate, journal (a resumed call yields its cached output once) and cost
  accounting exactly like `agent()`. Backed by a `StreamingAgentRunner` protocol that
  `DefaultAgentRunner` implements via pydantic-ai's `run_stream`; a non-streaming
  runner raises `WorkflowError`. Streamed calls emit `agent.start` / `agent.end` with
  `stream: True`. New exports: `stream`, `StreamHandle`, `StreamingAgentRunner`.
- **Typed generics** — `agent(output_type=T)` is now typed to return `T` (via
  `@overload`) instead of `Any`, and `@workflow` produces a `Workflow[OutputT]`
  inferred from the function's return annotation, so `await my_workflow(args)` is
  statically typed end-to-end with no casts.

## [26.06.3] - 2026-06-20

Dynamic Workflows — the durable-composition wave: sub-workflows, durable resume,
and human-in-the-loop (the top remaining SOTA gaps from the analysis).

### Added

- **Sub-workflows** — `subworkflow(name_or_wf, args)` runs another workflow inline,
  inheriting the parent's budget, concurrency gate, journal and runner (one
  deterministic sequence stream across the nested run). Emits `subworkflow.start` /
  `subworkflow.end`.
- **Durable resume** — `JournalBackend` protocol + `FileJournalBackend`. Attach one
  to a `Journal` (`Journal(backend=…, run_key=…)`) and every completed call flushes
  to durable storage, so an out-of-process crash resumes from the last call.
- **Human-in-the-loop** — `human(prompt)` pauses a run by raising `WorkflowInterrupt`;
  the caller `provide()`s the answer and re-runs with the same journal to resume past
  the pause. Sequence-keyed, so resume is deterministic; pairs with a `JournalBackend`
  for approvals that survive a restart. Emits `human.pause`.

### Fixed

- `WorkflowInterrupt` is in the never-swallow set, so a `human()` pause inside a
  `parallel`/`pipeline` branch propagates instead of being silenced.

## [26.06.2] - 2026-06-20

Dynamic Workflows: smart model routing, multi-model cost optimization, and the
budget/quality wiring that makes them observable. Driven by a SOTA gap analysis
(verdict: sound architecture, under-wired — the cost stack existed but wasn't
connected to the engine).

### Added

- **`SmartRoutingRunner`** — a drop-in `AgentRunner` that picks the cheapest
  *capable* model per call from ordered tiers, with fallback escalation on
  transient errors. Pluggable `ModelSelectionStrategy` (`ComplexityHeuristicStrategy`
  default — training-free; `CostFloorStrategy` — genai-prices cheapest). Emits
  `route.select` / `route.escalate` events. An explicit `agent(model=…)` always wins.
- **`cascade()`** — cheap-first, escalate-on-low-confidence (FrugalGPT-style),
  returning a `CascadeResult`; a judge model scores each tier by default. Emits
  `cascade.tier`.
- **USD + wall-clock budgets** — `WorkflowBudget(max_cost_usd=…, max_wall_seconds=…)`;
  `DefaultAgentRunner` now prices every call via `genai-prices` (`AgentCall.cost_usd`),
  and `WorkflowContext` exposes `cost_spent_usd` / `remaining_cost_usd()`.
- **`judge_panel()` / `Verdict`** — heterogeneous-model verification with a
  structured verdict. **`map_agents()`** — concurrent `map` sugar over `parallel`
  (removes the late-binding-lambda footgun). **`price_model()`** helper.

### Fixed

- **Budget kill-switch swallowed in `parallel`/`pipeline`.** A `WorkflowBudgetError`
  raised inside a fan-out branch resolved to `None` instead of aborting the run;
  structural/kill-switch errors now propagate (ordinary branch failures still
  resolve to `None`).
- **`run_id` collisions.** Default run id is now `f"{name}-{uuid4().hex[:8]}"`
  (was `f"{name}-run"`), so concurrent runs no longer merge in logs/telemetry.

## [26.06.1] - 2026-06-20

Completeness & wiring fixes for the new subsystems, validated end-to-end against a
real model (structured output, parallel fan-out, pipeline, a sub-agent calling a
toolset tool, budget enforcement, journal resume, adversarial verify, and a
connected workflow + secure-execution run).

### Added

- **Workflow sub-agents can use tools.** `agent()` (and the `AgentRunner` seam /
  `DefaultAgentRunner`) now accept `tools=` and `toolsets=`, so a workflow
  sub-agent can use a `ToolKit.as_toolset()`, an MCP server, or raw tools — just
  like a top-level agent. `deps` now also sets the underlying agent's `deps_type`.

### Fixed

- **Code Mode async tools.** `MontyEnvironment.run_code` now bridges async
  external functions (e.g. Firefly tools exposed via `toolkit_external_functions`)
  to sync, so sandboxed guest code calls them naturally without `await`. Previously
  an async tool returned an unresolved coroutine to the script.

## [26.06.0] - 2026-06-20

pydantic-ai modernization program (phase 1): dependency upgrade + deprecation /
stability fixes, two new headline subsystems (Dynamic Workflows, Secure Script
Execution), and native-capability adoption (message persistence, toolsets).

### Added

- **Dynamic Workflows engine** (`fireflyframework_agentic.workflows`) — a
  code-defined orchestration DSL over pydantic-ai agents, mirroring Claude's
  Workflow mechanism: `@workflow`, `agent`, `parallel` (barrier; failures → None),
  `pipeline` (streaming, no inter-stage barrier), `phase`, `log`; `WorkflowBudget`
  (concurrency / agent-count / token ceilings); `Journal` deterministic resume;
  pluggable `AgentRunner` (`DefaultAgentRunner` + test fakes); `workflow_registry`
  / `run_workflow`; verify combinators (`adversarial_verify`, `loop_until_dry`).
  See `docs/workflows.md`.
- **Secure Script Execution** (`fireflyframework_agentic.execution`, new
  `[script-execution]` extra) — run untrusted/generated Python in a self-hosted,
  deny-by-default sandbox. `ExecutionEnvironment` protocol; `MontyEnvironment`
  (pydantic-monty Rust micro-interpreter — no FS/network/env, host access only via
  registered external functions); `SecureScriptRunner` (validate → execute →
  capture with optional output scrubbing); `analyze_code`/`SafetyPolicy` AST
  pre-screen; `ExecutionLimits`; Firefly Code Mode (`toolkit_external_functions`).
  See `docs/execution.md`.
- **Native message persistence** — `model_utils.serialize_model_messages` /
  `deserialize_model_messages` (built on pydantic-ai's `ModelMessagesTypeAdapter`);
  `ConversationMemory` export/import now round-trips typed `ModelMessage` history
  losslessly (previously dropped as "not portable"). Backward-compatible with
  pre-existing exports.
- **Native toolsets** — `ToolKit.as_toolset()` returns a composable pydantic-ai
  `FunctionToolset`; `FireflyAgent(toolsets=...)` passes toolsets through to the
  underlying agent (enables `WrapperToolset`/`ApprovalRequiredToolset`/MCP servers).
- **Deprecation CI gate** — pytest promotes `pydantic`/`pydantic-ai` deprecation
  warnings to errors so a future dependency bump that reintroduces one fails CI
  immediately (the framework's own intentional `DeprecationWarning`s are unaffected).

### Changed

- **Upgraded pydantic-ai 1.99.0 → 1.107.0** and pinned `>=1.107.0,<2` (the
  previously-unbounded requirement could resolve to the breaking 2.0 line);
  `pydantic>=2.13,<3`; `pydantic-settings>=2.14.2,<3`.
- `AgentRunResult.usage` is now read as a property via the new
  `observability.usage.resolve_run_usage` helper (no `PydanticAIDeprecationWarning`),
  with forward-compatible support for method-style/legacy usage objects.
- `observability/decorators` use `inspect.iscoroutinefunction` (the `asyncio`
  variant is removed in Python 3.16); the content-based delegation router uses
  `instructions=` and is cached.

### Fixed

- **OutputGuardMiddleware** output sanitisation degraded results to a bare string
  (its `_replace` guard never matched the dataclass `AgentRunResult`), dropping
  usage/messages/type — now preserved via `dataclasses.replace`/NamedTuple/mutable
  handling.
- **RetryMiddleware** was a silent no-op — its configuration never reached the
  retry loop; a per-agent `RetryMiddleware` now takes effect.
- Cost (`_firefly_cost_usd`) was read for logging but never written — now wired
  from the recorded `UsageRecord`.
- Nullable/generic tool parameter annotations (`"str | None"`,
  `"dict[str, Any] | None"`) fell back to `str`, producing incorrect non-nullable
  JSON schemas for the LLM — now resolved correctly (`Optional`/union/generic forms).
- Removed the dead `ModelRetry` optional-import guard (pydantic-ai is a hard
  dependency).

## [26.05.33] - 2026-05-31

### Removed

- **BREAKING — REST/queue exposure layer.** Deleted the `fireflyframework_agentic.exposure`
  package (FastAPI app factory, HTTP/WS controllers, health probes, SSE, CORS/rate-limit/auth
  middleware, and Kafka/RabbitMQ/Redis consumer/producer hosts), the `rest`/`kafka`/`rabbitmq`/
  `redis`/`queues` extras, the `ExposureError`/`QueueConnectionError` exceptions, and the
  REST-serving config fields `auth_api_keys`/`auth_bearer_tokens`/`cors_allowed_origins`.
  Serving/hosting is now owned by the consuming service. The framework is a pure in-process
  library: it serves no port and consumes no broker.
- **BREAKING — service/infra observability.** Removed `observability.configure_exporters`
  (global OTel SDK provider/exporter wiring), the W3C trace-context propagation helpers
  (`inject_trace_context`/`extract_trace_context`/`get_trace_context`/`set_trace_context`/
  `trace_context_scope`), the `WebhookSink`, and the `otlp_endpoint` config field. The
  framework still emits model/agent spans/metrics via the OpenTelemetry API; configuring the
  SDK/exporters and cross-service trace propagation is now the host's responsibility.
- **BREAKING — inbound RBAC auth.** Removed `security.RBACManager`/`require_permission`, the
  `rbac_enabled`/`rbac_jwt_secret`/`rbac_multi_tenant` config fields, and the `pyjwt`
  dependency from the `security` extra (`cryptography` stays for `EncryptedMemoryStore`).
  Inbound-request authorization is a hosting concern owned by the service.

### Changed

- **`experiments`/`lab` documented as optional** leaf developer-tooling modules (no code or
  dependency change; they were already not imported by the core).

## [26.05.32] - 2026-05-31

### Fixed

- **`QdrantVectorStore.delete` is now namespace-scoped** — it deletes only points
  matching both the namespace and the requested ids (via a `FilterSelector`
  combining a `_namespace` `FieldCondition` with `HasIdCondition`), mirroring the
  namespace filter applied on search. Previously it deleted by a bare id list,
  ignoring the namespace.

### Changed

- **`scope_namespace` validates its inputs** — rejects empty components or
  components containing `/`, so distinct `(tenant_id, workspace_id)` scopes can
  never encode to a colliding namespace. The guard lives where the namespace is
  built rather than trusting callers.

## [26.05.31] - 2026-05-31

### Added

- **pgvector vector store** — `fireflyframework_agentic.vectorstores.PgVectorVectorStore`,
  an asyncpg-backed `BaseVectorStore` peer to the Chroma / Pinecone / Qdrant
  adapters. Owns its table with an HNSW cosine index, namespace-scoped storage,
  idempotent runtime schema bootstrap, and metadata filtering. Adds an
  overridable `_prepare_session(conn, *, namespace)` per-transaction hook (default
  no-op) for connection-level session setup — e.g. `SET LOCAL` for Postgres
  Row-Level Security GUCs. New optional extra `[vectorstores-pgvector]` (asyncpg);
  requires the `pgvector` extension on the server. This fills the only vector
  backend the framework was missing.
- **Tenant-scoped vector store layer** — `fireflyframework_agentic.vectorstores.scoped`:
  `ScopedVectorStore` (an explicit, fail-loud `Protocol` with required keyword-only
  `tenant_id` / `workspace_id`) and `TenantScopedVectorStore`, a backend-agnostic
  wrapper that folds `(tenant_id, workspace_id)` into the canonical
  `"t/<tenant>/w/<workspace>"` namespace (and stamps it onto document metadata),
  making **any** `VectorStoreProtocol` backend multi-tenant with one wrapper. Adds
  `scope_namespace` / `parse_scope_namespace` helpers. The existing
  single-namespace `VectorStoreProtocol` is unchanged (additive, non-breaking).

### Changed

- **`QdrantVectorStore`** now creates its collection on `initialise()` (cosine
  distance, sized to `vector_size`, idempotent) and exposes `close()`. Previously
  the collection had to be created out-of-band before the first `upsert`.

### Fixed

- **`QdrantVectorStore` search** now uses `query_points` instead of the removed
  `AsyncQdrantClient.search`, restoring compatibility with `qdrant-client`
  >= 1.12 (the method was dropped upstream).

## [26.05.30] - 2026-05-31

### Added

- **`fireflyframework_agentic.content.binary`** — a host-agnostic binary
  normalisation stack that turns uploaded files (PDF, Office, images,
  archives, emails) into consumer-ready `BinaryArtifact` rows for document
  loaders or multimodal LLMs. Plain classes + a `BinaryConfig` DTO (no DI
  framework), pluggable `OfficeConverter` (Gotenberg / LibreOffice / NoOp)
  via `build_office_converter`. New optional extra `[binary]`
  (pypdf, Pillow, pillow-heif, cairosvg, py7zr, extract-msg). This unifies
  the normalizers previously duplicated in the flycanon and flydocs services.

### Removed (BREAKING)

- **RAG subsystem** — deleted `fireflyframework_agentic.rag` (CorpusAgent,
  SqliteCorpus, StoredChunk, ChunkHit, HybridRetriever, reciprocal_rank_fusion,
  ingest/retrieval pipelines) and `tools.builtins.corpus_rag`. Consumers that
  used the corpus dataclasses / hybrid retriever should vendor them (flycanon
  now owns its `StoredChunk`/`ChunkHit`/`HybridRetriever` locally). The
  reusable `embeddings`, `vectorstores`, `content` and `storage` modules are
  unchanged.
- **MCP subsystem** — deleted `fireflyframework_agentic.exposure.mcp` (server,
  HTTP CLI, OAuth/Entra auth, transports), the `firefly-mcp-http` console
  script, and the `mcp` + `corpus-search` optional extras.
- **`corpus_search` example** and its docs (`corpus-search-overview`,
  `use-case-corpus-search`, `comparison-vs-qmd`, `deploy/mcp-corpus-auth`,
  `deploy/corpus-persistence`), the `.mcp.json.template`, and the MCP-server
  `Dockerfile`.
- **Azure deployment/infra** — removed the `deploy-mcp.yml` workflow (Azure
  Container Apps deploy of the MCP server), the Azurite / Azure-OIDC /
  Key Vault machinery from the nightly workflow, the `azure` optional extra
  (azure-identity / azure-keyvault-secrets / msal / azure-monitor exporter),
  the Application Insights / Azure Monitor OTel exporter from
  `observability.exporters` (observability stays vendor-neutral: console /
  OTLP), and the dead Entra ID config fields. **Kept** the `AzureEmbedder`
  Azure OpenAI model provider (`azure-embeddings` extra).
- **MarkItDown** — removed the Microsoft `markitdown` document converter:
  deleted `content.loaders` (`MarkitdownLoader` + the `loaders` package) and
  the `markitdown` optional extra. Services that relied on the universal
  MarkItDown loader now use native per-format loaders.
- Dead Azurite test fixture (and its `mcr.microsoft.com/azure-storage/azurite`
  image reference) and the stale corpus / MCP / Azure entries in
  `.env.template`.

### Changed

- `markdown-it-py` (used by `content.markdown_chunker`) is promoted from the
  removed `markitdown` extra to a core dependency.
- CI (`pr-gate`, `nightly`) install `--extra binary` and no longer install
  the removed `mcp` / `corpus-search` / `azure` / `markitdown` extras.

## [26.05.29] - 2026-05-29

### Added

- **State-based pipelines, unified on `PipelineEngine`.** `PipelineBuilder`
  gains an opt-in `state=` mode: pass a Pydantic model
  (`PipelineBuilder(name, state=SomeModel)`) and nodes become
  `async (state) -> dict | None` functions over a typed shared state instead
  of port-wired DAG steps. `add_node(fn)` derives the node id from
  `fn.__name__`, the first node added is auto-detected as the entry point, and
  the legacy port-based mode is unchanged. There is a single executor:
  `PipelineEngine` runs both modes — `PipelineBuilder(state=...)` simply
  constructs an engine configured with `state_schema`, `recursion_limit`,
  `audit_log`, `checkpointer`, `event_handler`, and any routers registered via
  `.branch(...)`. State-mode runs go through a cycle-aware frontier scheduler
  and execute independent nodes concurrently (#147, #245).
- **Reducers for merge semantics.** Field-level merge is declared with
  `Annotated[T, reducer]` on the state model. Four reducers ship from
  `fireflyframework_agentic.pipeline`: `replace` (default), `append`, `extend`,
  and `merge_dict`. Each node returns a partial dict and the engine folds it
  into shared state per the declared reducer, so concurrent fan-out workers
  accumulate rather than clobber.
- **Unified branching via `.branch(source, router, mapping=None)`.** One call
  replaces the legacy `BranchStep`/`FanOutStep` (now soft-deprecated with a
  `DeprecationWarning`). With no mapping the router returns a target node id
  directly; with a mapping it returns an abstract label that resolves to a
  node. `PipelineEngine.to_mermaid()` renders branch-edge labels from the
  registered mappings, and `DAG.to_mermaid()` / `DAG.to_json()` export any DAG.
- **Cycles and `Send` fan-out for agentic loops.** State-mode DAGs are built
  with `allow_cycles=True`, so a node can route back to itself (or an earlier
  node) for ReAct loops and retry-with-critique. A `recursion_limit` kwarg
  (default `25`) bounds runaway cycles with a clean failure result via a
  per-node visit counter. A router may return `list[Send]` (`Send(target,
  payload)`) for runtime fan-out: each worker runs concurrently over its own
  payload-merged state copy and the results reduce back into shared state, with
  per-target visit counters preserved for observability.
- **Human-in-the-loop pause gates.** A node returning the `Pause(reason=...)`
  sentinel halts the pipeline cleanly and writes a paused checkpoint
  (`CheckpointRecord` gains backward-compatible `paused` / `pause_reason`
  fields). The result carries `paused` / `paused_node` / `pause_reason`, and an
  event handler can observe `on_node_pause`. Pauses are sticky: resuming
  requires `invoke(run_id=..., approve_pause=True)`, which restarts from the
  successor of the paused node; resuming without it raises `PipelineError`.
- **Checkpoint, resume, and mid-pipeline entry.** `FileCheckpointer` persists
  state after each successful node; `invoke(run_id=...)` resumes from the latest
  checkpoint, skipping completed nodes. `invoke(state, start_at=node)` jumps
  into a pipeline mid-flow with an explicit state — useful for replays and
  partial reruns.
- **Pipeline audit log.** New `pipeline/audit.py` exports a split protocol —
  `AuditLog` (write-only) and `QueryableAuditLog` (adds `list_entries`) — over
  an `AuditEntry` model, plus three concrete backends that wrap stdlib /
  framework primitives: `FileAuditLog` (JSONL per pipeline + run id,
  queryable), `LoggingAuditLog`, and `OtelAuditLog`. Every node visit is
  recorded with its status, including `paused`.
- **Unified `EventHandler` protocol and OTel spans.** A single `EventHandler`
  protocol (with `PipelineEventHandler` as the built-in implementation) covers
  both pipeline modes. State-mode spans use the `pipeline.state.*` taxonomy so
  existing observability dashboards keep working.
- **`examples/software_factory/` example.** A self-contained package that
  exercises the headline state-mode features end to end: typed state with
  reducers, router-driven branching with a `qa → codegen` cycle
  (`recursion_limit=3`), checkpoint/resume on a transient builder failure, and
  `StatePipelineEventHandler` progress output. It also ships plug-and-play
  durable backends — `checkpointers/{postgres,redis}.py` and
  `audit/postgres.py`, each a flat ~50–80 LOC class against a caller-supplied
  connection — swappable via the `FIREFLY_CKPT` env var.
- **Contradiction surfacing in the corpus answerer.** Both the fast-path and
  reasoning prompts gain a MUST rule: when two or more retrieved chunks
  disagree on the same fact, the answer must surface the conflict and cite the
  competing sources rather than silently picking one. Verified against
  contradicting fixtures (e.g. the same quarter's revenue reported as two
  different figures).

### Changed

- **Durable checkpointer / audit backends now live in examples, not the
  framework.** `PostgresCheckpointer`, `RedisCheckpointer`, and
  `PostgresAuditLog` (and the internal `PsycopgBackend` helper) have been
  dropped from the framework; the `psycopg[binary]` dependency is removed from
  the `[postgres]` extra. The `Checkpointer` and `AuditLog` protocols plus the
  framework-native `FileCheckpointer`, `FileAuditLog`, `LoggingAuditLog`, and
  `OtelAuditLog` remain. Operators who need a database-backed store implement
  the protocol against their own connection — see the ~50–80 LOC reference
  classes under `examples/software_factory/`.

### Fixed

- **`IngestLedger` now records fetch failures.** A failed fetch previously
  advanced the cursor without writing anything, so files silently disappeared
  from the ledger. Each failure is now recorded so retries and audits can
  observe it (#219).
- **`StructuredRetriever` works on cloud backends.** The retriever was
  hardcoded to `self.root / "corpus.sqlite"`, which broke on
  `AzureBlobBackend` where the SQLite database lives in blob storage. It now
  routes through `_db_store.ensure_fresh()`, materialising a local copy on
  cloud backends and remaining a no-op on `LocalBackend` (#219).
- **`firefly-mcp-http` now wires OpenTelemetry exporters at startup.** A
  `_configure_telemetry()` helper runs at the top of `main()`, before any
  framework code records a measurement, so when
  `APPLICATIONINSIGHTS_CONNECTION_STRING` is set the metrics and traces
  actually reach Application Insights. Resolves the operator-reported "App
  Insights is empty despite the connection string being set".

### Changed (dependencies)

- **`pydantic-ai` upgraded `1.75 → 1.99` and `mistralai` un-pinned.** With
  `mistralai` back on PyPI (2.4.5), the `[tool.uv.sources]` git workaround is
  removed and the `pydantic-ai` floor is lifted to `>=1.99.0`. The `Mistral`
  import now targets the 2.x layout (`mistralai.client`).

### Internal

- **Inline imports lifted to module top-level across the codebase** for
  project-rule compliance, with optional-dependency imports guarded via
  `TYPE_CHECKING` so pyright narrows correctly without importing at runtime.
  No behavioural change.
- **PR-gate CI sped up** with shallow checkout, no coverage on PRs, and a
  cached `uv` resolver across jobs (#218).
- **Cost-tracking docs** now point users at `examples/cost_tracking.py` for the
  cost-resolver override pattern.
## [26.05.21] - 2026-05-21

### Changed (BREAKING — delegation routing API)

- **`DelegationStrategy.select()` replaced by `decide() -> RoutingDecision`.**
  Strategies now return ranked, scored `Candidate` tuples plus metadata
  instead of a single agent. No deprecation shim: a shim would lock in
  the single-agent return shape we are explicitly escaping. External
  implementers get a clean `Protocol` mismatch at type-check time.
  `DelegationRouter.route()` keeps its exact current signature, so the
  common call site is unaffected. New combinators `ChainStrategy`,
  `FallbackStrategy`, and `WeightedStrategy` nest strategies without
  subclassing; `DelegationRouter.decide()` / `execute()` split selection
  from execution and emit a `firefly.routing.decision` OTel event.
- **`CapabilityStrategy` and `ContentBasedStrategy` now return empty
  decisions instead of raising / silently falling back.** Previously
  `CapabilityStrategy` raised `DelegationError` on no-match (blocking
  composition with fallback) and `ContentBasedStrategy` silently
  returned the first agent on LLM failure (hiding errors). Both now
  return empty `RoutingDecision` objects. Callers using bare
  `router.route()` still see `DelegationError("Empty routing
  decision")` from `execute()` — same exception class, different
  message.
- **`CostAwareStrategy` no longer carries a hardcoded model→tier
  table.** Cost per agent is computed via `resolve_cost` from
  `fireflyframework_agentic.observability.cost_resolvers` against a
  synthetic `CostContext` (defaults: 1000 input / 500 output tokens),
  and scores are pool-relative linear normalisations. New keyword
  arguments configure the sample tokens, the resolver chain, and the
  `on_unknown` policy (`"skip"` / `"lowest"` / `"raise"`).

### Added

- **Tool-using corpus answer agent.** `CorpusAgent` gains an
  `answer_strategy: Literal["fast", "reasoning"] = "fast"` constructor
  flag. The fast path is unchanged (one-shot expand → retrieve → rerank
  → answer); the reasoning path delegates the answer phase to a new
  `ReasoningAnswerAgent` (in `fireflyframework_agentic.rag.retrieval`)
  that runs a tool-using ReAct loop over four tools:
  `knowledge_search`, `sql_query`, `inspect_table`, and a restricted
  Python `python_compute` sandbox. Construction adds three tunables
  (`max_reasoning_tool_calls`, `max_reasoning_llm_calls`,
  `reasoning_wall_clock_seconds`). Default behaviour is unchanged.
- **`Answer.reasoning_trace`** — new optional field of type
  `ReasoningTrace | None` (default `None`). Populated by
  `ReasoningAnswerAgent` when `CorpusAgent.query(..., include_trace=True)`
  is set. Every `ActionStep` carries `tool_name + tool_args` (a plain
  dict), so a recorded trace is re-executable: see
  `tests/examples/corpus_search/test_trace_is_replayable.py`.
- **MCP `corpus_query` tool** gains two optional params, `strategy` and
  `include_trace`. `include_trace` defaults to `True` — callers that hit
  the reasoning path receive the typed `ReasoningTrace` in the response
  without opting in. The fast path never populates a trace regardless of
  the flag, so the legacy fast-path JSON shape is unchanged. Pass
  `include_trace=false` to opt out (smaller payload). Process-wide agent
  cache keys by `(corpus_id, strategy)` so both paths can coexist for the
  same corpus.
- **New optional extra `[reasoning-eval]`** pulls in `numpy>=2.0` and
  `pandas>=2.2` for the `python_compute` sandbox. The sandbox itself is
  AST-validated (denylist on dunder names, `eval`/`exec`/`compile`/
  `__import__`/`open`/`input`, attribute access to dunder names like
  `__class__`/`__bases__`), runs in a worker thread with a 5 s wall-clock
  timeout, and caps combined stdout + result rendering at 8 KB.
- **Reasoning telemetry.** Two new OTel instruments: histogram
  `firefly.rag.reasoning.tool_call_duration` (labelled by `tool_name`)
  and counter `firefly.rag.reasoning.terminal_state` (labelled by
  outcome — `answered | no_info | tool_limit | llm_limit | timeout |
  error`). The existing `firefly.rag.query` span gains a
  `firefly.rag.answer_strategy` attribute on both fast and reasoning
  paths.

### Changed (BREAKING — internal layout)

- **Per-corpus token store is now provider-agnostic in the framework.**
  `fireflyframework_agentic.security.corpus_token` exports a
  `CorpusTokenStore` Protocol plus the in-memory `CorpusTokenCache` and
  the `corpus_token_digest` helper. The Azure-specific
  `KeyVaultTokenStore` + `build_default_store` factory moved to
  `examples/corpus_search/azure_security.py` alongside the existing
  Entra/OBO code. The `firefly-mcp-http` server resolves the concrete
  store at startup via the `FIREFLY_MCP_TOKEN_STORE_FACTORY` env var
  (defaults to `examples.corpus_search.azure_security:build_default_store`)
  so existing Azure deployments keep working, and operators on a
  different back-end can swap the factory without touching the
  framework. The `firefly-mcp-token` CLI moved to
  `examples/corpus_search/firefly_mcp_token.py` and is no longer
  registered as a top-level script; invoke it as
  `python -m examples.corpus_search.firefly_mcp_token …`.

### Changed (BREAKING for clients of the auth flag)

- **`firefly-mcp-http` per-corpus auth now requires the
  `X-Firefly-Corpus-Id` header on every gated request** (in addition to
  `Authorization: Bearer …`). The middleware validates the bearer against
  Key Vault before letting any request through — including the
  JSON-RPC handshake, `tools/list`, and `list_corpora` — closing the gap
  where an outsider could enumerate tool schemas or corpus_ids by
  sending only a bearer-shaped string. Body-side `arguments.corpus_id`
  must match the header value for corpus-scoped tools. Update Claude
  Desktop / `mcp-remote` entries to pass `--header
  X-Firefly-Corpus-Id: <id>`.

### Fixed

- **SQL agent reasoning: discriminator filters, parent-level GROUP BY, and
  sibling-column scans.** The text-to-SQL retriever now annotates each
  string column in the schema context with its
  `COUNT(DISTINCT)` cardinality (e.g. `metric_line (string, 3 distinct)`)
  so the agent can spot categorical / discriminator axes and parent-vs-
  child cardinality gaps at schema-read time. The system prompt gains
  three rules and three worked examples covering: filtering on a
  discriminator before aggregating heterogeneous rows (#161), using
  `GROUP BY <parent>` when the user says "by X" / "for each X" / "per
  X" (#162), and scanning semantically-related sibling columns before
  concluding "no record" on a NULL result (#163). No new tools or
  schema-model fields.

- **`firefly-mcp-http` now loads `.env` on startup.** The CLI calls
  `load_dotenv(find_dotenv(usecwd=True))` at the top of `main()`, so a
  developer running the server from a project directory gets its
  variables (e.g. `EMBEDDING_MODEL`, `FIREFLY_MCP_KEYVAULT_URL`)
  without an explicit shell `source`. Real process env vars always win
  — `load_dotenv` defaults to `override=False` — so Azure /
  Container Apps deployments (which inject env from the manifest
  before the process starts) see no behavioural change. `python-dotenv`
  is now a core dependency (previously declared only under the
  `corpus-search` / `dev` extras); promoted so the import in `main()`
  can be unconditional rather than guarded. Resolves the `KeyError:
  'EMBEDDING_MODEL'` operators hit when running `firefly-mcp-http`
  locally with a `.env` present.

- **`firefly-mcp-http` logs unhandled asyncio task exceptions to stderr
  before the loop has a chance to die silently.** Previously, an
  exception in a task scheduled on the asyncio loop (request-cleanup
  callbacks, fire-and-forget tool work, SSE long-poll teardown) was
  routed by ``BaseEventLoop`` to the ``asyncio`` logger at ERROR — but
  uvicorn's default log config doesn't surface that logger. Operators
  saw "the server died" / "the bridge can't reconnect" with no
  traceback. The CLI now installs a loop-level exception handler that
  routes through ``logging.getLogger("…http_cli")`` (which
  ``basicConfig`` wires up at startup, level overridable via
  ``FIREFLY_MCP_LOG_LEVEL``), preserving the exception's traceback via
  ``exc_info=``. Does NOT swallow exceptions or change loop behaviour
  — only makes them visible.

- **LocalBackend corpus state now lives under `CORPUS_ROOT`, not in
  `~/.cache/`.** `DatabaseStore` previously kept its working copy at
  `~/.cache/fireflyframework_agentic/dbstore/<store_id>/db.sqlite` for
  every backend, and `LocalBackend.upload`/`download` `shutil.copyfile`'d
  between that cache and the file under `CORPUS_ROOT`. The two copies
  could drift, and a `rm -rf $CORPUS_ROOT` did **not** reset corpus state
  (the dedup ledger and embeddings stayed alive in the cache,
  re-ingestion silently skipped every file). The store now reads
  `StorageBackend.local_path` at construction; for `LocalBackend` it
  co-locates the working copy with the backend file (same inode, no
  duplicate), and every file used by a corpus — SQLite, WAL/SHM, the
  metadata sidecar, the lock sentinel — lives under the configured
  root. `LocalBackend.upload` / `download` short-circuit when source
  and destination are the same inode, so the existing call sites
  needed no changes. Remote backends (`AzureBlobBackend`) keep the
  legacy cache-dir layout because their working copy MUST be a separate
  local file. Operators upgrading should
  `rm -rf ~/.cache/fireflyframework_agentic/dbstore/corpus_search:` to
  reclaim disk; the new layout takes effect automatically on next
  startup (#170).

- **Answerer preserves diacritical marks in non-English responses.** The
  RAG answerer's instructions now tell the model to answer in the same
  language as the question and to keep correct orthography
  (`á`/`é`/`í`/`ó`/`ú`/`ñ`/`ü`/`ç`/`à`/`è`/`ê`/`ô` and equivalents)
  rather than transliterating to ASCII. Resolves the regression where
  Spanish answers came back as `produccion`/`aprobacion`/`Cual?` instead
  of `producción`/`aprobación`/`¿Cuál?` (#157).

### Added

- **`list_corpus_schemas` and `corpus_sql` MCP tools.** Two new read-only
  entrypoints that expose the structured side of a corpus directly,
  without going through the LLM-driven `corpus_query` pipeline.
  `list_corpus_schemas(corpus_id)` returns every `TargetSchema` saved by
  `ingest_corpus_structured` (column names, types, primary/foreign keys,
  units) so a host can discover what's queryable; `corpus_sql(corpus_id,
  sql, params?, limit?)` runs a single `SELECT` and returns raw rows.
  Safety: the connection is opened in SQLite `mode=ro` so writes
  physically cannot land, the SQL is parsed with sqlglot and only
  `SELECT` is accepted, and table references are whitelisted against the
  schema registry — internal tables (`chunks`, `_schemas`, `ingestions`,
  …) are rejected. Adds `sqlglot>=26.0.0` to the `corpus-search` extra.
- **Optional `unit` field on `ColumnSpec`.** Schemas can now declare the
  human-readable unit a numeric column stores (`"USD millions"`,
  `"headcount"`, `"percent"`, `"days"`, …). The SQL retriever's schema
  context surfaces it to the agent as `name (type, unit=…)`, the
  retriever's system prompt requires the agent to preserve the unit in
  SELECT results (via alias or co-selection), and the answerer is
  instructed to quote the unit alongside any numeric quantity it cites
  — or to flag the ambiguity explicitly when no unit is known, rather
  than presenting a unit-less number the user cannot verify (#158).
- **`firefly-mcp-token` CLI** for operators managing per-corpus tokens
  in Azure Key Vault. Commands: `create`, `rotate`, `revoke`, `list`,
  `show-name`. Uses `DefaultAzureCredential`; the minted token goes to
  stdout (pipe-friendly), status to stderr. Registered as a
  `[project.scripts]` entry alongside `firefly-mcp-http`.
- **Fuzzy entity matching in the SQL retriever.** The agentic inspect-loop
  gains a `find_similar` op on `inspect_table` that tokenises the user's
  value on whitespace and matches accent-folded, case-insensitive
  substrings (AND-of-LIKEs, with OR fallback). A new `unaccent_lower(col)`
  SQL UDF is registered on every connection so the LLM can write
  diacritic-tolerant filters in `run_select`. The system prompt now
  steers the LLM to probe `find_similar` for free-text entity columns
  and to retry rather than stop when an equality filter returns 0 rows.
- **`numeric_summary` op on `inspect_table` in the SQL retriever.** Returns
  total rows, non-null count, null count, sum, min, max, and *two* mean
  variants — `mean_excluding_nulls` (SQL default `AVG`) and
  `mean_blanks_as_zero` (treats NULL cells as 0). The two means diverge
  whenever the column carries NULLs, so the agent can detect the
  blank-as-zero spreadsheet convention and pick the right
  interpretation instead of silently averaging over the smaller
  non-null subset. The system prompt now steers the LLM to probe
  `numeric_summary` before averaging numeric columns, and to surface
  both interpretations when ambiguous.
- **Per-corpus capability tokens for `firefly-mcp-http`.** When
  `FIREFLY_MCP_CORPUS_AUTH_ENABLED=true`, every MCP tool call must
  present a bearer matching the `firefly-mcp-corpus-token-<corpus_id>`
  secret in the Azure Key Vault at `FIREFLY_MCP_KEYVAULT_URL`. A token
  leak now exposes one corpus, not the whole server. `list_corpora` is
  filtered to the caller's authorised corpora. Off by default; stdio
  transport and existing ingress-fronted HTTP deployments are
  unaffected. See `docs/deploy/mcp-corpus-auth.md`.

## [26.05.11] - 2026-05-11

### Changed (BREAKING)

- **Repo layout flattened.** `src/fireflyframework_agentic/` moved to
  `fireflyframework_agentic/` at the repo root. Vendor- and example-specific
  code (`cli/`, vendor backends, SharePoint source, the `corpus_search`
  reference agent's CLI) moved under `examples/corpus_search/`. The
  `storage-azure` extra and the previous top-level `[project.scripts]`
  block were removed (#134, #137).
- **`corpus_retrieve` → `knowledge_search`.** The MCP corpus retrieval tool
  was renamed for clarity (#134). Update any client code or MCP wiring that
  referenced `corpus_retrieve`.
- **`firefly-mcp-http` entry point relocated.** Now registered as
  `fireflyframework_agentic.exposure.mcp.http_cli:main` in
  `[project.scripts]`. The MCP HTTP server is a first-class deliverable of
  the package, not an example (#139). Closes #138.

### Added

- **Unified structured + unstructured ingestion in `corpus_search`.**
  `CorpusAgent.ingest_source` accepts both tabular and document sources
  through a single pipeline, with separate retrievers feeding the
  answerer's prompt (#108).
- **Schema-aware structured ingestion.** Discover-review-ingest workflow
  for tabular sources: schema discovery first, then per-column review,
  then ingest only the approved columns. Closes #117 (#118).
- **`RubricReviewer`.** Rubric-based grader loop for validation; LLM judges
  candidate outputs against an explicit rubric and feeds back deltas for
  retry. Exposed from `validation` (#130).
- **Managed SQLite storage backends.** Local-file and Azure Blob backends
  expose a uniform managed-SQLite surface for memory and other persistence
  needs (#112).
- **`list_corpora` MCP tool.** Discovery endpoint that enumerates available
  corpora; nightly e2e test added to keep it honest (#115).

### Fixed

- **Nightly auth via Key Vault + OIDC.** Replaced direct
  `${{ secrets.ANTHROPIC_API_KEY }}` injection with `azure/login` (OIDC)
  followed by `az keyvault secret show` against `kv-firefly-signature`.
  The previous wiring resolved to empty strings and broke every
  Anthropic-using test on the nightly (#120, follow-up #137). Closes #125.
- **MCP container deploy.** Repaired the `Dockerfile` `COPY` paths and
  console-script entry point so `deploy-mcp` builds and pushes again
  after the flat-layout move (#139). Closes #138.
- **Retrieval benchmark.** `runner.py` now ingests only `*.md` files; the
  25,870-row billing-ledger CSV was being fed through the markdown
  chunker, producing ~24k chunks and corrupting the SQLite-vec store.
  Smoke test updated for the 12-doc corpus (#140).
- **Structured ingest folder walks.** Filter to tabular file types so
  non-tabular files in mixed corpora don't trip the structured loader
  (#123).
- **Real-LLM e2e tests.** Switched `test_e2e_real_llm` to Azure OpenAI
  embeddings to align with the production embedder path (#119).

### Changed

- **No hardcoded VERSION constants in installers.** `install.sh`,
  `install.ps1`, and their `uninstall.*` counterparts no longer carry a
  hand-bumped `VERSION` string; the post-install verify reads
  `fireflyframework_agentic.__version__` from package metadata (#136).
- **`.python-version` removed.** `pyproject.toml`'s
  `requires-python = ">=3.13"` is the sole source of truth (#136).
- **`CLAUDE.md` gitignored.** Developer-local agent guidance is no longer
  tracked (#136).
- **Dependabot bumps.** `urllib3` 2.6.3 → 2.7.0 (#135);
  `langchain-core` 1.3.2 → 1.3.3 (#124).
- **CI hardening.** `deploy-mcp.yml` bumped `actions/checkout@v4 → @v6`
  and SHA-pinned `docker/setup-buildx-action` to v4.0.0 to clear the
  Node 20 deprecation (#137).

### Tests

- **`tests/examples/corpus_search/` consolidated.** Vendor backend tests
  and the structured-ingestion ledger test moved under the example's tree
  alongside their production code (#110, #111).
- **Benchmark smoke test** updated to assert the new 12-md corpus shape
  after the runner fix (#140).

## [26.04.30] - 2026-04-30

### Added

- **Entra ID security.** Token verification and on-behalf-of (OBO) exchange
  for Azure AD authentication flows. New `[azure]` extra installs the
  required dependencies (#92).
- **MCP server.** New exposure module ships an MCP server and the
  `firefly-mcp` CLI for exposing agents over the Model Context Protocol
  (#93).
<!--
The hexagonal ingestion module described in #84 (RawFile/TypedRecord
ports, SharePointSource, DuckDBSink, firefly-ingest CLI, [ingestion-*]
extras) did not ship in v26.04.30 -- the source tree at HEAD has no
`fireflyframework_agentic/ingestion/` package and `pyproject.toml` does
not register `firefly-ingest` as a script. Track in a follow-up release.
-->

- **Corpus-search example agent.** New `examples/corpus_search/` ships a
  folder-ingestion + hybrid-search agent: `markitdown` → chunk → embed
  (Azure OpenAI by default) → SQLite FTS5 + Chroma. Query pipeline is
  expand (Haiku) → BM25 + vector → RRF fuse → rerank (Haiku) → answer
  (Sonnet) with inline citations. Framework additions:
  `content/loaders/MarkitdownLoader` and
  `pipeline/triggers/FolderWatcher`. New extras: `[markitdown]`,
  `[watch]`, `[corpus-search]` (#82).
- **SQLite memory store.** New `SQLiteStore` provides stdlib-backed local
  persistence for memory, sitting alongside `FileStore` with the same
  surface (#87).
- **Refactored prompt manager.** New prompt implementation with template
  scheme, registry, and explicit `Prompt` type used by reasoning prompts
  (#85).
- **Nightly CI workflow.** Full test suite runs once per day under the
  `nightly` pytest marker, separated from the per-PR `pr-gate`. On
  failure, the workflow opens (or comments on) a `nightly-failure`
  tracking issue; a subsequent green run auto-closes it. README gains a
  Nightly badge alongside PR gate (#89).

### Changed

- **Security extra renamed.** `entra.py` → `azure.py`; the security manager
  now inherits from `RBACManager`. Extra `[entra]` → `[azure]` and is
  installed in the PR gate.
- **Memory store layout.** `SQLiteStore` lives in `store.py` and is aligned
  with the other stdlib backends.
- **`EmbeddingResult.usage` is now `Optional`.** Backward-compatible change
  to support embedding backends that do not report usage (#82).
- **Examples simplified.** Use bare `load_dotenv()` and source `MODEL` from
  `.env`; removed `examples/_common.py` (#81).
- **CI rename.** Workflow `ci` → `pr-gate`; triggers only on
  `pull_request`, not on `push`.

### Fixed

- **Nightly perf benchmarks.** Replaced the broken
  `benchmark(lambda: pytest.asyncio.fixture(coro))` pattern with sync
  tests driven by a shared `bench_loop` event-loop fixture (required so
  `HttpTool`'s `httpx.AsyncClient` stays bound to a single loop across
  iterations). Test classes dropped per project convention; `skipif` and
  `benchmark(group=...)` decorators moved onto each function (#91).

### Tests

- **Test tree reorganized** under `tests/unit/` for agents, memory,
  observability, pipeline, tools, resilience, and core (#88).
- **Responsible AI category** (`tests/responsible_ai/`) groups
  `output_guard` and `prompt_guard`.
- **Benchmarks moved** to `tests/performance/`, marked `nightly`, and
  renamed to `test_bench_*.py` for pytest collection.
- **Tests README** documents per-category descriptions and the nightly
  marker.

## [26.04.28] - 2026-04-28

### Changed (BREAKING)

- **Project rename: `fireflyframework-genai` → `fireflyframework-agentic`.**
  Comprehensive rebrand from `genai` to `agentic` across every public surface.
  See `MIGRATION` section below for an upgrade checklist.
  - Python module: `fireflyframework_genai` → `fireflyframework_agentic`.
  - PyPI package: `fireflyframework-genai` → `fireflyframework-agentic`.
  - Class names: `FireflyGenAI*` → `FireflyAgentic*` (covers `FireflyGenAIConfig`
    and `FireflyGenAIError`).
  - Environment-variable prefix: `FIREFLY_GENAI_*` → `FIREFLY_AGENTIC_*`.
  - REST factory: `create_genai_app()` → `create_agentic_app()`.
  - Repository URLs: `github.com/fireflyframework/fireflyframework-genai` →
    `…/fireflyframework-agentic`.
  - Brand prose: "Firefly GenAI" → "Firefly Agentic".

  Mentions of "GenAI" as a *category* (e.g. "GenAI metaframework", "GenAI
  workloads", `keywords = ["genai"]`) are intentionally preserved -- the
  framework targets the GenAI domain. References to the external
  `genai-prices` library and the `GenAIPricesCostCalculator` wrapper class
  also remain.

### Removed (BREAKING)

- **Studio extracted to its own repository.** The visual IDE, project runtime,
  scheduler, tunnel, code generation, and AI assistant now live in
  [fireflyframework-agentic-studio](https://github.com/fireflyframework/fireflyframework-agentic-studio).
  Removed from this repo:
  - `src/fireflyframework_agentic/studio/` (Python module).
  - `studio-frontend/` (SvelteKit SPA).
  - `studio-desktop/` (Tauri desktop bundle and PyInstaller spec).
  - `scripts/build_studio.py`.
  - `tests/test_studio/` (~30 test files).
  - Studio-only docs: `studio.md`, `studio-agents.md`, `api-reference.md`,
    `scheduling.md`, `tunnel-exposure.md`, `input-output-nodes.md`,
    `project-api.md`, `tutorial-bpm-pipeline.md`.
  - `examples/studio_launch.py`.
  - `.github/workflows/desktop.yml` (Tauri build pipeline).
  - `[studio]` extra in `pyproject.toml` (FastAPI, Uvicorn, Strawberry-GraphQL,
    APScheduler).
  - `firefly` CLI entry point (now ships with the studio package).
  - `frontend-build` job and studio artifact wiring in CI.

### Added

- **Pre-commit hooks.** `.pre-commit-config.yaml` with ruff (lint + format),
  file hygiene (trailing whitespace, EOF, YAML/TOML/JSON validation,
  merge-conflict markers, large-file guard, AST check), `gitleaks` for secret
  scanning, and `no-commit-to-branch` for `main`/`master`. CI gains a
  `Pre-commit` job that runs the same hooks on every PR so `--no-verify`
  bypasses are caught.

### Migration

```diff
- pip install fireflyframework-genai
+ pip install fireflyframework-agentic
```

```diff
- from fireflyframework_genai import FireflyGenAIConfig, get_config
+ from fireflyframework_agentic import FireflyAgenticConfig, get_config

- from fireflyframework_genai.exposure.rest import create_genai_app
+ from fireflyframework_agentic.exposure.rest import create_agentic_app
```

```diff
- FIREFLY_GENAI_DEFAULT_MODEL=...
+ FIREFLY_AGENTIC_DEFAULT_MODEL=...
```

For users who previously installed the embedded Studio:

```diff
- pip install "fireflyframework-genai[studio]"
+ pip install fireflyframework-agentic-studio
```

A bulk replace covers most call sites:

```bash
grep -rl 'fireflyframework_genai' . | xargs sed -i 's/fireflyframework_genai/fireflyframework_agentic/g'
grep -rl 'fireflyframework-genai' . | xargs sed -i 's/fireflyframework-genai/fireflyframework-agentic/g'
grep -rl 'FireflyGenAI'           . | xargs sed -i 's/FireflyGenAI/FireflyAgentic/g'
grep -rl 'FIREFLY_GENAI_'         . | xargs sed -i 's/FIREFLY_GENAI_/FIREFLY_AGENTIC_/g'
```

The full migration guide for Studio users lives in the
[fireflyframework-agentic-studio README](https://github.com/fireflyframework/fireflyframework-agentic-studio#migration-from-fireflyframework-agenticstudio).

### Changed

- **Middleware Protocol** -- Renamed `before`/`after` to `before_run`/`after_run`
  on `PromptCacheMiddleware` and `CircuitBreakerMiddleware` to conform to the
  `AgentMiddleware` protocol contract.
- **Exception Hierarchy** -- Renamed `MemoryError` to `FireflyMemoryError` to
  avoid shadowing the Python built-in.  A deprecated alias is kept for backwards
  compatibility.
- **Quota Defaults** -- `quota_enabled` now defaults to `False` to avoid
  unexpected enforcement on first install.
- **Cost Calculator Type** -- `cost_calculator` config field is now
  `Literal["auto", "genai_prices", "static"]`.

### Security

- **ShellTool** -- Replaced `create_subprocess_shell` with
  `create_subprocess_exec` to prevent command-injection via shell metacharacters.
- **FileSystemTool** -- Replaced `str.startswith` path check with
  `Path.is_relative_to` to prevent symlink-based path traversal.
- **RBAC Decorator** -- Fixed `require_permission` to use `inspect.signature`
  for positional argument binding and replaced `nonlocal` mutation with local
  `manager` variable.
- **Encryption** -- Each `AESEncryptionProvider.encrypt()` call now generates a
  random 16-byte salt for PBKDF2 key derivation, stored as
  `salt[16]+nonce[12]+ciphertext+tag`.
- **REST Middleware** -- `allow_credentials` is now automatically set to `False`
  when `allow_origins=["*"]`.  API key comparison uses `hmac.compare_digest`.
- **REST Router** -- Exception details are no longer exposed to clients; errors
  are logged server-side and a generic message is returned.
- **Database Store** -- Schema name is validated against `^[a-zA-Z_][a-zA-Z0-9_]*$`
  to prevent SQL injection.
- **FileStore** -- Added `Path.is_relative_to` check in `_path()` to prevent
  namespace-based path traversal.

### Fixed

- **Thread Safety** -- Added `threading.Lock` to `InMemoryStore`, `CachedTool`,
  `RateLimitGuard`, `ConversationMemory.get_turns/get_total_tokens/clear/
  clear_all/new_conversation/conversation_ids`.
- **Pipeline Engine** -- `_gather_inputs` now correctly extracts `output_key`
  from dict and object results.  `started_at` is initialised before the retry
  loop.
- **asyncio.run Crash** -- `database_store.py` and `manager.py` sync wrappers
  now detect a running event loop and offload to a `ThreadPoolExecutor` instead
  of crashing.
- **TextTool ReDoS** -- Regex operations in `_extract`, `_replace`, `_split` now
  run via `asyncio.to_thread` with a 5-second timeout.
- **SandboxGuard ReDoS** -- User-supplied patterns are compiled with a safe
  `_safe_compile` helper.
- **Observability Decorators** -- `@metered` now records latency in a `finally`
  block so it is captured even on exceptions.
- **Logging** -- `ColoredFormatter.format` now operates on a `copy.copy(record)`
  to avoid mutating shared log records.
- **SlidingWindowManager** -- Uses `collections.deque` and `_running_tokens`
  counter instead of re-estimating the entire window on every eviction.
- **PromptTemplate** -- Added `_UNSET` sentinel for `PromptVariable.default` so
  that `default=None` is correctly propagated.
- **Queue Consumers** -- Kafka, RabbitMQ, and Redis consumers now wrap
  `_process_message` in try/except to prevent one bad message from killing the
  consumer loop.
- **Goal Decomposition** -- `_execute_task` now passes `memory=memory` to the
  delegated `_task_pattern.execute()`.
- **ConversationMemory** -- `clear()` and `clear_all()` now also clear
  `_summaries` to prevent stale summary leaks.
- **Reasoning Registry** -- Six built-in patterns are auto-registered at import
  time.
- **Observability Exports** -- `extract_trace_context`, `inject_trace_context`,
  and `trace_context_scope` are now re-exported from `observability/__init__.py`.
- **UsageTracker** -- `_check_budget` exception handler now logs at DEBUG instead
  of silently passing.

## [26.02.07] - 2026-02-17

### Added

- **Multi-Provider Support Hardening** -- New `model_utils` module providing
  centralized model identity extraction (`extract_model_info`,
  `get_model_identifier`, `detect_model_family`) for uniform handling of both
  `"provider:model"` strings and `pydantic_ai.models.Model` objects across the
  framework's observability and resilience layers.

- **Cross-Provider Cost Tracking** -- `StaticPriceCostCalculator` now resolves
  pricing through proxy providers. `bedrock:anthropic.claude-3-5-sonnet-latest`
  maps to Anthropic pricing, `azure:gpt-4o` maps to OpenAI pricing, and
  `ollama:*` models report `$0.00`. Added Mistral pricing entries.

- **Bedrock Throttling Detection** -- `_is_rate_limit_error()` now detects
  AWS Bedrock `ThrottlingException` and `TooManyRequestsException` (boto3
  `ClientError` shapes) in addition to HTTP 429 and string-pattern matching.
  Also added `"throttl"` as a fallback string pattern.

- **Cross-Provider Prompt Caching** -- `PromptCacheMiddleware` now uses
  `detect_model_family()` to route caching configuration by model family
  rather than string matching. `bedrock:anthropic.claude-*` correctly routes
  to Anthropic caching; `azure:gpt-*` routes to OpenAI caching.

- **Model Object Fallback** -- `FallbackModelWrapper` now accepts
  `Sequence[str | Model]`, allowing cross-provider fallback chains with
  pre-configured `Model` objects (e.g. Azure → OpenAI → Anthropic).
  `run_with_fallback()` updates `_model_identifier` on each swap so cost
  tracking and rate-limit backoff keys remain accurate.

## [26.01.01] - 2026-02-10

### Changed

- **CalVer Migration** -- Migrated versioning scheme from `M.YY.Patch` to
  `YY.MM.Patch` for clearer calendar-based version identification. This
  release consolidates all changes from the previous `2.26.x` releases.

## [2.26.1] - 2026-02-09

### Removed

- **Studio / CLI / TUI** -- Removed the Firefly GenAI Studio package
  (`src/fireflyframework_genai/studio/`), the `flygenai` CLI entry point,
  the `[cli]` optional extra, all studio tests (`tests/test_studio/`), and
  studio documentation (`docs/studio.md`). The framework is now a pure
  library without any CLI or TUI components. Room persistence configuration
  fields have been removed from `FireflyGenAIConfig`.

## [2.26.1] - 2026-02-08

### Added

- **Database Persistence Backends** -- PostgreSQL and MongoDB support for
  production-grade conversation memory and working memory persistence.
  `PostgreSQLStore` and `MongoDBStore` implement the `MemoryStore` protocol
  with connection pooling via `asyncpg` and `motor`. Automatic schema/collection
  creation on first use. Configuration via environment variables or direct
  initialization. Install with `pip install fireflyframework-genai[postgres]`
  or `pip install fireflyframework-genai[mongodb]`.

- **Distributed Trace Correlation** -- W3C Trace Context propagation across
  service boundaries (HTTP, message queues, pipelines). Functions
  `inject_trace_context()` and `extract_trace_context()` for manual
  propagation. Automatic integration with REST API middleware, Kafka/RabbitMQ/
  Redis queue consumers, and pipeline context via `correlation_id`. Enables
  end-to-end trace correlation in distributed GenAI applications.

- **API Quota Management** -- Production-grade quota enforcement with
  `QuotaManager`, `RateLimiter`, and `AdaptiveBackoff`. Supports daily budget
  limits (USD), per-model rate limits (requests/minute), and exponential
  backoff with jitter for 429 responses. Sliding window rate limiting for
  accurate enforcement. Configuration via environment variables
  (`FIREFLY_GENAI_QUOTA_*`). Integrates with `UsageTracker` for unified cost
  and quota management.

- **Security Hardening** -- Four new security features for enterprise deployments:
  1. **RBAC** -- Role-Based Access Control with JWT authentication, role/permission
     management, multi-tenant isolation, and `@require_permission` decorator.
  2. **Encryption** -- AES-256-GCM encryption for data at rest via
     `AESEncryptionProvider` and `EncryptedMemoryStore` wrapper for transparent
     encryption of any `MemoryStore` backend.
  3. **SQL Injection Prevention** -- Automatic detection and blocking of 15+
     SQL injection patterns in `DatabaseTool` queries. Enforces parameterized
     queries and rejects string concatenation.
  4. **CORS Security** -- Restrictive CORS policy by default (no origins allowed).
     Explicit allow-list configuration for production via environment variables.

- **HTTP Connection Pooling** -- `HttpTool` now supports connection pooling via
  `httpx.AsyncClient` for 50-70% latency reduction on repeated requests.
  Configurable pool size, keepalive connections, and timeout. Automatic fallback
  to `urllib` when `httpx` not installed. Configuration via environment variables
  (`FIREFLY_GENAI_HTTP_POOL_*`). Async context manager support for cleanup.

- **Incremental Streaming** -- True token-by-token streaming mode for `FireflyAgent`.
  New `streaming_mode` parameter accepts `"buffered"` (default, chunk-based) or
  `"incremental"` (token-by-token). Incremental mode provides `stream_tokens()`
  method with optional `debounce_ms` parameter. REST API endpoints:
  `/agents/{name}/stream` (buffered) and `/agents/{name}/stream/incremental`.
  Both modes work with all middleware.

- **Batch Processing** -- `BatchLLMStep` for pipeline batch processing of multiple
  prompts through an agent concurrently. Supports both initial inputs and previous
  step outputs via flexible `prompts_key` parameter. Configurable batch size,
  completion polling, and per-batch callbacks. Automatic error handling captures
  individual prompt failures without blocking the batch. Respects all agent
  middleware including caching and circuit breakers.

- **Provider Prompt Caching** -- `PromptCacheMiddleware` enables provider-specific
  prompt caching for 90-95% cost reduction on cached tokens. Supports Anthropic
  (`cache_control`), OpenAI (`cached_content`), and Gemini (`cachedContent`)
  caching mechanisms. Automatic configuration based on model provider. Cache
  statistics tracking with hit rate and estimated savings calculation. Configurable
  system prompt caching, minimum token threshold, and TTL.

- **Circuit Breaker Pattern** -- `CircuitBreaker` and `CircuitBreakerMiddleware`
  for resilient agent execution. Three states: CLOSED (healthy), OPEN (rejecting
  requests), HALF_OPEN (testing recovery). Configurable failure threshold,
  recovery timeout, and success threshold. Prevents cascading failures and allows
  failing services time to recover. `CircuitBreakerOpenError` raised when circuit
  is open. Metrics tracking via `get_metrics()`.

- **Integration Test Suite** -- 11 comprehensive integration tests in
  `tests/integration/test_full_integration.py` covering all production features
  working together: agent with all middleware, streaming with middleware, pipeline
  with batch processing, memory persistence, circuit breaker with batch processing,
  cost guard with streaming, multiple agents sharing memory, and feature
  composition scenarios.

- **Examples and Documentation** -- Updated examples showing all features in
  production context: `examples/full_integration.py` (comprehensive production
  agent with all middleware), `examples/circuit_breaker.py` (resilience patterns),
  `examples/batch_processing.py` (batch API usage). Updated documentation in
  `docs/agents.md`, `docs/pipeline.md`, `docs/memory.md`, `docs/observability.md`,
  `docs/security.md`, and `docs/tools.md` with detailed usage examples and
  configuration guides.

### Fixed

- **Pipeline Data Flow** -- `BatchLLMStep` now correctly accesses previous step
  outputs via `context.get_node_result()` with fallback to `inputs` dict. Supports
  both node-to-node data flow and initial input patterns.

- **Streaming API** -- Fixed `UsageTracker` API usage in streaming tests (changed
  from `get_all()` to `get_summary()`). Fixed async generator cleanup to prevent
  `StopAsyncIteration` errors.

### Changed

- **Middleware Count** -- Updated documentation from "eight" to "ten" built-in
  middleware classes to include `PromptCacheMiddleware` and `CircuitBreakerMiddleware`.

- **Defence-in-Depth Example** -- Updated production middleware stack example to
  include prompt caching and circuit breaker alongside existing security and
  observability middleware.

## [2.26.0] - 2026-02-07

### Added

- **Agent Middleware System** -- Pluggable before/after hooks for agent runs via
  `AgentMiddleware` protocol and `MiddlewareChain`. Supports prompt mutation,
  result transformation, and cross-cutting concerns (audit, guardrails, logging).
- **Agent Run Timeout** -- `timeout` parameter on `FireflyAgent.run()` and
  `run_sync()` backed by `asyncio.wait_for()`.
- **Model Fallback** -- `FallbackModelWrapper` and `run_with_fallback()` for
  automatic retry with backup models on failure.
- **Result Caching** -- `ResultCache` with TTL, LRU eviction, and
  hash(model+prompt) keying for deduplicating identical agent calls.
- **Conversation Summarisation** -- `ConversationMemory` now accepts a
  `summarizer` callback; oldest turns are evicted and summarised when token
  usage exceeds the threshold.
- **JSON Structured Logging** -- `JsonFormatter` and `format_style="json"`
  option on `configure_logging()` for machine-parseable log output.
- **Prompt Injection Guard** -- `security.PromptGuard` with 10 default
  regex-based injection patterns, optional sanitisation, max-length check,
  and extensible custom patterns.
- **REST Rate Limiting** -- `RateLimiter` and `add_rate_limit_middleware()`
  for sliding-window per-client rate limiting on FastAPI/Starlette apps.
- **Async Memory I/O** -- `FileStore` gains `async_save`, `async_load`,
  `async_load_by_key`, `async_delete`, `async_clear` wrappers via
  `asyncio.to_thread()` to avoid blocking the event loop.
- **Pipeline Eager Scheduling** -- `PipelineEngine` replaced level-by-level
  `asyncio.gather()` with a task-queue approach using `asyncio.create_task()`
  and `asyncio.wait(FIRST_COMPLETED)` so nodes start as soon as their
  upstream dependencies complete.
- **Metering & Cost Tracking** -- Automatic token usage tracking, cost
  estimation, and budget enforcement across agents, reasoning patterns, and
  pipelines. `UsageTracker`, `CostCalculator` protocol with static and
  `genai-prices` backends, budget alerts and limits.
- **Streaming Usage Tracking** -- `run_stream()` wrapped in
  `_UsageTrackingStreamContext` to capture usage on `__aexit__`.
- **Pipeline Error Propagation** -- `FailureStrategy` enum (`PROPAGATE`,
  `SKIP_DOWNSTREAM`, `FAIL_PIPELINE`) on `DAGNode` with transitive
  successor skipping.
- **Thread-Safe Registries** -- `threading.Lock` added to `AgentRegistry`,
  `ToolRegistry`, `ReasoningPatternRegistry`, and `ConversationMemory`.
- **Config Cross-Validation** -- `@model_validator` on `FireflyGenAIConfig`
  enforcing budget, chunk-overlap, and QoS constraints.
- **Type Safety** -- Replaced `Any` with concrete types (`UsageSummary`,
  `FireflyAgent`, `MemoryManager`) in `pipeline/result.py`,
  `pipeline/context.py`, `agents/delegation.py`; fixed `Protocol` import
  in `pipeline/steps.py`.
- **Comprehensive Test Suite** -- 509 tests covering all modules including
  middleware, fallback, cache, config validation, JSON logging, lifecycle,
  agent/tool decorators, guards, composers, toolkit, observability
  decorators/events, pipeline builder/steps/context, plugin discovery,
  memory summarisation, prompt guard, rate limiter, and async FileStore.

## [2.25.0] - 2026-02-07

### Added

- **Logging** -- `configure_logging` function for structured framework-wide logging
  with level, format, and handler configuration.
- **Examples** -- 15 runnable example scripts in `examples/` covering agents (basic,
  conversational, summarizer, classifier, extractor, router), all six reasoning patterns
  (CoT, ReAct, Reflexion, Plan-and-Execute, ToT, Goal Decomposition), reasoning
  pipeline and memory integration, and a complex IDP pipeline.
- **IDP Pipeline Example** (`examples/idp_pipeline.py` + `idp_tools.py`) -- Full
  Intelligent Document Processing pipeline that downloads a real 33-page Unilever PDF
  and processes it through a 7-node DAG: ingest → split → classify → extract →
  validate → assemble → explain. Features LLM-powered document splitting (detects 4
  sub-documents), `create_classifier_agent` with category descriptions,
  `OutputReviewer` with custom retry prompts, `GroundingChecker` validation,
  LLM-powered explainability narrative generation, ANSI-colored pretty JSON output,
  `TraceRecorder` / `AuditTrail` / `ReportBuilder` integration, and exercises all
  major framework features together.
- **Core** -- Configuration management via Pydantic Settings, typed enumerations,
  structured exception hierarchy, and a plugin discovery system.
- **Agents** -- Pydantic AI agent wrapper with lifecycle management, a central
  registry, round-robin and capability-based delegation strategies, execution context,
  and the `@firefly_agent` decorator.
- **Tools** -- Protocol-driven tool interface, fluent `ToolBuilder`, `ToolRegistry`,
  `ToolKit` grouping, guard system (validation, rate-limiting, approval, sandboxing),
  sequential/fallback/conditional composition, `@firefly_tool` decorator, and built-in
  tools for HTTP, filesystem, search, database, and shell operations.
- **Prompts** -- Jinja2-based `PromptTemplate` engine, versioned `PromptRegistry`,
  sequential/conditional/merge composition strategies, variable validation, and
  file/directory loaders.
- **Reasoning Patterns** -- Abstract `ReasoningPattern` with Template Method design,
  `ReasoningTrace` for step-by-step audit, a pattern registry, and a composable
  pipeline. Ships six patterns: ReAct, Chain of Thought, Plan-and-Execute, Reflexion,
  Tree of Thoughts, and Goal Decomposition.
- **Observability** -- OpenTelemetry-native `FireflyTracer`, `FireflyMetrics` counter
  and histogram helpers, `FireflyEvents` event emitter, configurable exporters, and
  `@traced` / `@metered` decorators.
- **Explainability** -- `TraceRecorder` for decision-level recording, `ExplanationGenerator`
  for natural-language summaries, `AuditTrail` for compliance, and `ReportBuilder`
  for Markdown and JSON reports.
- **Experiments** -- `Experiment` and `Variant` models, `ExperimentRunner` for executing
  A/B tests, `ExperimentTracker` for persistence, and `ExperimentComparator` for
  statistical analysis.
- **Lab** -- `LabSession` for interactive exploration, `Benchmark` for performance
  measurement, `Comparison` for side-by-side evaluation, `Dataset` for test data
  management, and `Evaluator` protocol for custom scoring.
- **Exposure REST** -- FastAPI application factory, auto-generated agent routes,
  request-ID and CORS middleware, health-check endpoints, and SSE streaming.
- **Exposure Queues** -- Abstract consumer/producer model with Kafka, RabbitMQ, and
  Redis Pub/Sub implementations, plus a pattern-based message router.
- **Installation Scripts** -- Cross-platform interactive installers (`install.sh`,
  `uninstall.sh`, `install.ps1`, `uninstall.ps1`) with TUI, requirement detection,
  and remote execution support via `curl | bash` and `irm | iex`.
- **Documentation Index** -- Professional `docs/README.md` landing page with
  documentation map organized by architecture layer.

[26.01.01]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v26.01.01
[2.26.1]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v2.26.1
[2.26.0]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v2.26.0
[2.25.0]: https://github.com/fireflyframework/fireflyframework-genai/releases/tag/v2.25.0
