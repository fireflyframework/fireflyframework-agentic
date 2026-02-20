# Examples

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Runnable example scripts demonstrating the major features of `fireflyframework-genai`.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- An OpenAI API key (set `OPENAI_API_KEY` or enter it when prompted)

All examples use the model `openai:gpt-4o`.

## Running

From the repository root:

```bash
export OPENAI_API_KEY="sk-..."
uv run python examples/<example_name>.py
```

If `OPENAI_API_KEY` is not set, each script will prompt you interactively.

## Agent Examples

- **`basic_agent.py`** — Create a `FireflyAgent` with instructions and tags, run a prompt.
- **`conversational_memory.py`** — Multi-turn conversation with `MemoryManager` and `create_conversational_agent`.
- **`summarizer.py`** — `create_summarizer_agent` with tuneable length, style, and format.
- **`classifier.py`** — `create_classifier_agent` with categories and `ClassificationResult` structured output.
- **`extractor.py`** — `create_extractor_agent` with a custom Pydantic model for structured data extraction.
- **`router.py`** — `create_router_agent` with an agent map and `RoutingDecision` structured output.

## Security Examples

- **`security_guards.py`** — `PromptGuard` and `OutputGuard` standalone scanning. Demonstrates injection detection, PII/secrets/harmful content scanning, sanitise mode, custom deny patterns, and max output length. **No API key required.**

## Tool Examples

- **`cached_tool.py`** — `CachedTool` wrapping a slow tool with TTL-based memoisation. Shows cache hits/misses, TTL expiry, `invalidate()`, `clear()`, and `max_entries` eviction. **No API key required.**
- **`tool_timeout.py`** — `BaseTool(timeout=...)` per-tool execution timeout and `ToolTimeoutError` handling. Shows fast/slow/no-timeout tools and graceful fallback patterns. **No API key required.**

## Memory Examples

- **`conversation_export_import.py`** — `export_conversation()` and `import_conversation()` for conversation backup, migration, and restoration. Also demonstrates `create_llm_summarizer()`. **No API key required** for export/import.

## Observability Examples

- **`observability_usage.py`** — `UsageTracker` with bounded `max_records`, cumulative cost tracking, per-agent and per-correlation summaries. **No API key required.**

## Delegation Examples

- **`delegation_strategies.py`** — `DelegationRouter` with all four strategies: `RoundRobinStrategy`, `CapabilityStrategy`, `CostAwareStrategy`, and `ContentBasedStrategy` (LLM routing).

## Pipeline Examples

- **`pipeline_branching.py`** — `BranchStep` for conditional routing in a DAG, `PipelineEventHandler` for live progress, and `DAGNode.backoff_factor` for exponential retry backoff. **No API key required.**

## Complex Examples

- **`idp_pipeline.py`** _(+ `idp_tools.py`)_ — Full **Intelligent Document Processing** pipeline that downloads a real 33-page PDF (Unilever Certificate of Incorporation & Bylaws) and processes it end-to-end through a **7-node DAG**: `ingest → split → classify → extract → validate → assemble → explain`. Exercises **all major framework features** together:
  - **Agents** — `FireflyAgent`, `create_classifier_agent` (with category descriptions), `create_extractor_agent`
  - **Tools** — `@firefly_tool`, `ToolKit`, `CachedTool` (TTL-based memoisation of PDF downloads), tool-to-agent bridging via `as_pydantic_tools()`
  - **Security** — `PromptGuardMiddleware` (injection detection/sanitisation), `OutputGuardMiddleware` (PII/secrets/harmful content scanning), `CostGuardMiddleware` (budget tracking in warn-only mode)
  - **Prompts** — `PromptTemplate` with declared variables (split, classification, extraction, explainability)
  - **Reasoning patterns** — `ReflexionPattern` for validation self-correction
  - **Content processing** — `TextChunker`, `ContextCompressor`, `TruncationStrategy`
  - **Memory** — `MemoryManager` with working memory and conversation memory
  - **Validation** — `OutputValidator`, `GroundingChecker`, `OutputReviewer` (custom retry prompt), field rules, cross-field rules
  - **Pipeline DAG** — `PipelineBuilder`, `CallableStep`, `.chain()`, `PipelineEngine`, `PipelineEventHandler` (live progress logging)
  - **Document splitting** — LLM-powered boundary detection splits the PDF into 4 sub-documents, each processed independently
  - **Explainability** — `TraceRecorder`, `AuditTrail`, `ReportBuilder`, plus an LLM agent that generates a comprehensive human-readable narrative
  - **Pretty JSON output** — ANSI-colored JSON rendering with key/value colour differentiation
  - **Logging** — `configure_logging`

  Requires `pdfplumber` (included in dev dependencies).

## Studio Examples

- **`studio_launch.py`** — Launch Firefly Studio programmatically with custom `StudioConfig`. Shows how to embed the Studio app with a custom port, host, and project directory. Requires `pip install "fireflyframework-genai[studio]"`. **No API key required** (the AI assistant requires one, but the IDE itself does not).

## Reasoning Pattern Examples

- **`reasoning_cot.py`** — Chain of Thought: step-by-step reasoning with `ReasoningThought` and trace inspection.
- **`reasoning_react.py`** — ReAct: Reason-Act-Observe loop via `run_with_reasoning()`.
- **`reasoning_reflexion.py`** — Reflexion: Execute-Reflect-Retry with `ReflectionVerdict` self-critique.
- **`reasoning_plan.py`** — Plan-and-Execute: structured planning with `PlanStepDef` status tracking.
- **`reasoning_tot.py`** — Tree of Thoughts: parallel branch exploration with `BranchEvaluation` scoring.
- **`reasoning_goal.py`** — Goal Decomposition: hierarchical `GoalPhase` breakdown and task execution.
- **`reasoning_pipeline.py`** — Pipeline: chaining Chain-of-Thought into Reflexion with a merged trace.
- **`reasoning_memory.py`** — Memory: reasoning with `MemoryManager` working memory enrichment.
