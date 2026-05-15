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

"""Tool-using corpus answer agent.

See spec ``docs/superpowers/specs/2026-05-14-tool-using-corpus-agent-design.md``.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fireflyframework_agentic.rag._telemetry import reasoning_tool_call_duration

if TYPE_CHECKING:
    from fireflyframework_agentic.rag.agent import CorpusAgent
    from fireflyframework_agentic.rag.corpus import ChunkHit
    from fireflyframework_agentic.rag.ingest.structured_schema import TargetSchema
    from fireflyframework_agentic.rag.retrieval.sql import (
        SqlRetrievalOutcome,
        StructuredRetriever,
    )


@dataclass(slots=True)
class _LoopContext:
    """Mutable per-query state shared by the four tool closures.

    Built fresh on each :meth:`ReasoningAnswerAgent.answer` call. Closures grab
    it through :data:`_CURRENT_CTX`. Production callers MUST NOT touch this
    type directly — the asserts in each closure will fire.
    """

    corpus_agent: CorpusAgent | None
    structured_retriever: StructuredRetriever | None
    schemas: list[TargetSchema]
    db_path: Path
    accumulated_hits: dict[str, ChunkHit] = field(default_factory=dict)
    sql_calls: list[SqlRetrievalOutcome] = field(default_factory=list)


_CURRENT_CTX: contextvars.ContextVar[_LoopContext | None] = contextvars.ContextVar(
    "reasoning_answerer_ctx", default=None
)


_SNIPPET_CHARS = 400


def _record_tool_duration(tool_name: str, t0: float) -> None:
    """Record wall-clock elapsed ms for one tool call, labelled by tool_name.

    Pulled out to keep the closures readable — every tool wraps its body in
    a ``try / finally`` that calls this on exit, success or failure.
    """
    reasoning_tool_call_duration.record(
        (time.monotonic() - t0) * 1000.0,
        {"tool_name": tool_name},
    )


def _build_knowledge_search():
    """Return an async ``knowledge_search(query, top_k=5)`` closure.

    Closes over the contextvar — callers must :meth:`answer` first. Side-effect:
    every returned :class:`ChunkHit` is recorded in
    ``ctx.accumulated_hits[chunk_id]`` so the orchestrator can enrich
    ``Answer.cited_sources`` post-hoc.
    """

    async def knowledge_search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "knowledge_search called outside answer()"
        assert ctx.corpus_agent is not None
        t0 = time.monotonic()
        try:
            hits = await ctx.corpus_agent.retrieve(query, top_k=top_k, rerank=True)
        finally:
            _record_tool_duration("knowledge_search", t0)
        out: list[dict[str, Any]] = []
        for h in hits:
            ctx.accumulated_hits[h.chunk_id] = h
            out.append(
                {
                    "chunk_id": h.chunk_id,
                    "source_path": h.source_path,
                    "score": h.score,
                    "snippet": h.content[:_SNIPPET_CHARS],
                }
            )
        return out

    return knowledge_search


def _build_sql_query():
    """Return an async ``sql_query(question)`` closure wrapping
    :meth:`StructuredRetriever.retrieve`.

    Returns a JSON-serialisable dict so the LLM sees a clean shape. Side-effect:
    appends the :class:`SqlRetrievalOutcome` to ``ctx.sql_calls`` for telemetry.
    """

    async def sql_query(question: str) -> dict[str, Any]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "sql_query called outside answer()"
        assert ctx.structured_retriever is not None
        t0 = time.monotonic()
        try:
            outcome = await ctx.structured_retriever.retrieve(question, ctx.schemas)
        finally:
            _record_tool_duration("sql_query", t0)
        ctx.sql_calls.append(outcome)
        return {
            "outcome": outcome.outcome,
            "attempted_sql": outcome.attempted_sql,
            "result_markdown": outcome.result_markdown,
            "probe_trail": [
                {"table": p.table, "column": p.column, "op": p.op, "result": p.result} for p in outcome.probe_trail
            ],
        }

    return sql_query


def _build_inspect_table_tool():
    """Return an async ``inspect_table(table, column, op, value=None)`` closure
    that delegates to the SQL retriever's existing inspect primitives.

    Builds a one-off SQL ``_LoopContext`` per call; the SQL retriever's probe
    trail is not interesting at the outer layer — the outer trace already
    captures each ``inspect_table`` call as its own :class:`ActionStep`.
    """

    from fireflyframework_agentic.rag.retrieval.sql import (
        _build_inspect_tool,
    )
    from fireflyframework_agentic.rag.retrieval.sql import (
        _LoopContext as _SqlLoopContext,
    )

    async def inspect_table(
        table: str,
        column: str,
        op: Literal[
            "distinct_values",
            "count",
            "sample_rows",
            "value_range",
            "find_similar",
            "numeric_summary",
        ],
        value: str | None = None,
    ) -> str:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "inspect_table called outside answer()"
        sql_ctx = _SqlLoopContext(db_path=ctx.db_path, schemas=ctx.schemas)
        inspect_fn = _build_inspect_tool(sql_ctx)
        t0 = time.monotonic()
        try:
            return await inspect_fn(table, column, op, value)
        finally:
            _record_tool_duration("inspect_table", t0)

    return inspect_table


def _build_python_compute_tool():
    """Return an async ``python_compute(source, data=None)`` closure.

    Runs the sandbox in the event loop's default executor so the worker thread
    inside :func:`run_python_compute` doesn't block other tool calls.
    """
    import asyncio as _asyncio

    from fireflyframework_agentic.rag.retrieval._python_compute import run_python_compute

    async def python_compute(source: str, data: dict[str, Any] | None = None) -> str:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "python_compute called outside answer()"
        loop = _asyncio.get_running_loop()
        t0 = time.monotonic()
        try:
            return await loop.run_in_executor(None, run_python_compute, source, data)
        finally:
            _record_tool_duration("python_compute", t0)

    return python_compute


_OBS_CAP = 2000

# pydantic-ai exposes the structured-output handoff as an implicit tool
# call (default name "final_result"). That's internal plumbing — the
# Answer itself carries the final content, so surfacing it as an
# ActionStep would be noise and would confuse trace replay (no tool
# closure to call back into).
_PYDANTIC_AI_OUTPUT_TOOL_NAMES: frozenset[str] = frozenset({"final_result"})


def _truncate_obs(text: str) -> str:
    if len(text) <= _OBS_CAP:
        return text
    return text[:_OBS_CAP] + f"… ({len(text) - _OBS_CAP} more bytes)"


def _trace_from_messages(messages, *, pattern_name: str):
    """Translate pydantic-ai message history into a typed :class:`ReasoningTrace`.

    Skips system and user prompts (those are our own); emits:
    - ``TextPart`` → :class:`ThoughtStep`
    - ``ToolCallPart`` → :class:`ActionStep` (tool_name + tool_args lossless)
    - ``ToolReturnPart`` → :class:`ObservationStep` (content truncated to 2 KB)
    """
    from pydantic_ai.messages import (
        SystemPromptPart,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    from fireflyframework_agentic.reasoning.trace import (
        ActionStep,
        ObservationStep,
        ReasoningTrace,
        ThoughtStep,
    )

    trace = ReasoningTrace(pattern_name=pattern_name)
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, (SystemPromptPart, UserPromptPart)):
                continue
            if isinstance(part, TextPart):
                if part.content:
                    trace.add_step(ThoughtStep(content=part.content))
            elif isinstance(part, ToolCallPart):
                if part.tool_name in _PYDANTIC_AI_OUTPUT_TOOL_NAMES:
                    continue
                args = part.args if isinstance(part.args, dict) else {}
                trace.add_step(ActionStep(tool_name=part.tool_name, tool_args=args))
            elif isinstance(part, ToolReturnPart):
                if part.tool_name in _PYDANTIC_AI_OUTPUT_TOOL_NAMES:
                    continue
                trace.add_step(
                    ObservationStep(
                        content=_truncate_obs(str(part.content)),
                        source=part.tool_name,
                    )
                )
    return trace


_SYSTEM = """\
You answer questions about a corpus by calling tools to retrieve and verify evidence.

Available tools:
  - knowledge_search(query, top_k=5)  — hybrid retrieval over unstructured docs;
    returns chunks with chunk_id, source_path, score, snippet. Cite chunks
    inline using [chunk_id] notation for claims grounded in them.
  - sql_query(question)  — natural-language text-to-SQL over the structured
    tables. Returns {outcome, attempted_sql, result_markdown, probe_trail}.
  - inspect_table(table, column, op, value=None)  — cheap direct SQL probes
    (no inner LLM). op in {distinct_values, count, sample_rows, value_range,
    find_similar, numeric_summary}. Use BEFORE committing to sql_query when
    you are not sure what values a column contains.
  - python_compute(source, data=None)  — restricted Python sandbox (multi-line,
    stdlib + numpy + pandas). Use this for ANY arithmetic that appears in your
    answer. Pass numbers from prior tool observations as the ``data`` dict so
    the snippet is self-contained and the trace is reproducible.

Strategy:
  1. Probe cheap before committing expensive: inspect_table < sql_query.
  2. For any answer involving sums, averages, ratios, percentages, growth
     rates, comparisons, or rankings, you MUST call python_compute. Do not
     attempt arithmetic in prose — models are unreliable at it, and the
     python_compute trace is the only way a reader can verify the numbers.
  3. SQL-grounded claims should name the source table. Knowledge-grounded
     claims must carry inline [chunk_id] citations.
  4. If neither retrieval nor SQL surfaces evidence, reply exactly:
     "I don't have enough information."
  5. When two or more chunks (or chunk vs SQL row) contradict each other
     on the same fact, you MUST surface the conflict explicitly. State each
     claim with its citation side by side and name the disagreement. Do not
     pick one as the answer without a basis grounded in the data itself
     (e.g., one source explicitly supersedes the other; or one carries a
     clear authority signal the user can verify). If you pick one, name
     the basis. Silently choosing the first or most confident-sounding
     source is the wrong move — the user must be able to see the
     disagreement.

Answer in the same language as the question; preserve diacritics (á, é, ñ, ç,
…). When you report a numeric quantity, include its unit if known.
"""


class ReasoningAnswerAgent:
    """Tool-using corpus answer agent. See spec §4.

    Owns a :class:`FireflyAgent` registered with the four tool closures and
    ``output_type=Answer``. Pydantic-ai handles the loop; we translate the
    resulting message history to a :class:`ReasoningTrace` and enrich
    ``cited_sources`` from accumulated knowledge_search hits.
    """

    def __init__(
        self,
        *,
        model,
        corpus_agent,
        structured_retriever,
        schema_registry,
        db_path: Path,
        max_tool_calls: int = 20,
        max_llm_calls: int = 10,
        wall_clock_seconds: float = 120.0,
    ) -> None:
        from fireflyframework_agentic.agents import FireflyAgent
        from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent

        self._model = model
        self._corpus_agent = corpus_agent
        self._structured_retriever = structured_retriever
        self._schema_registry = schema_registry
        self._db_path = db_path
        self._max_tool_calls = max_tool_calls
        self._max_llm_calls = max_llm_calls
        self._wall_clock = wall_clock_seconds

        self._knowledge_search = _build_knowledge_search()
        self._sql_query = _build_sql_query()
        self._inspect_table = _build_inspect_table_tool()
        self._python_compute = _build_python_compute_tool()

        self._agent = FireflyAgent(
            name="reasoning_answerer",
            model=model,
            output_type=Answer,
            instructions=_SYSTEM,
            tools=[
                self._knowledge_search,
                self._sql_query,
                self._inspect_table,
                self._python_compute,
            ],
            auto_register=False,
        )

        # Fallback synthesiser used when the reasoning loop runs out of budget.
        # Re-uses the same model so the user gets the same answer-writing
        # behaviour they'd get on the fast path, but operates over whatever
        # evidence (chunks + the last SQL outcome) the loop managed to gather
        # before the budget hit. Without this, a budget-exhausted run returns
        # an apology instead of the grounded answer the data already supports.
        self._fallback_answerer = AnswerAgent(model=model)

    async def answer(self, question: str, *, include_trace: bool = False):
        import asyncio
        import logging

        from pydantic_ai.usage import UsageLimits

        from fireflyframework_agentic.rag._telemetry import reasoning_terminal_state
        from fireflyframework_agentic.rag.retrieval.answerer import (
            Answer,
            _build_cited_sources,
        )
        from fireflyframework_agentic.rag.retrieval.sql import _build_schema_context

        log = logging.getLogger(__name__)

        schemas = await self._schema_registry.list_schemas()
        ctx = _LoopContext(
            corpus_agent=self._corpus_agent,
            structured_retriever=self._structured_retriever,
            schemas=schemas,
            db_path=self._db_path,
        )
        schema_context = _build_schema_context(schemas, self._db_path) if schemas else ""
        prompt = (f"{schema_context}\n\n" if schema_context else "") + f"Question: {question}"

        tok = _CURRENT_CTX.set(ctx)
        budget_exhausted_label: str | None = None
        result = None
        try:
            run = self._agent.run(
                prompt,
                usage_limits=UsageLimits(
                    tool_calls_limit=self._max_tool_calls,
                    request_limit=self._max_llm_calls,
                ),
            )
            result = await asyncio.wait_for(run, timeout=self._wall_clock)
        except TimeoutError as exc:
            log.warning("reasoning_answerer loop ended early (timeout): %s", exc)
            budget_exhausted_label = "timeout"
        except Exception as exc:  # noqa: BLE001 — graceful-degradation contract
            # UsageLimitExceeded is the most likely landing here; everything
            # else (network, model error) is rolled up under "error". We
            # label tool-limit and llm-limit separately because they're
            # operator-tunable.
            label = "error"
            exc_name = type(exc).__name__
            if "UsageLimit" in exc_name:
                msg = str(exc).lower()
                if "tool" in msg:
                    label = "tool_limit"
                elif "request" in msg:
                    label = "llm_limit"
            log.warning("reasoning_answerer loop ended early (%s): %s", label, exc)
            budget_exhausted_label = label
        finally:
            _CURRENT_CTX.reset(tok)

        if budget_exhausted_label is not None:
            reasoning_terminal_state.add(1, {"outcome": budget_exhausted_label})
            # Graceful degradation. Hand whatever evidence we managed to
            # gather to the fast-path synthesiser — it knows how to write
            # a grounded Answer from (hits, sql_outcome), short-circuits
            # to "I don't have enough information." when both are empty,
            # and is the same path the user would have taken on the fast
            # strategy. The user always gets a real answer; the budget
            # label is preserved in telemetry and the warning log above.
            last_sql = ctx.sql_calls[-1] if ctx.sql_calls else None
            try:
                fallback = await self._fallback_answerer.answer(
                    question,
                    list(ctx.accumulated_hits.values()),
                    sql_outcome=last_sql,
                )
            except Exception as exc:  # noqa: BLE001 — final defence
                # Synthesiser also crashed (model error, network blip).
                # Return a structured response so callers still get an
                # Answer-shaped object — never raise out of answer().
                log.warning("reasoning_answerer fallback synthesiser also failed: %s", exc)
                fallback = Answer(
                    text=(
                        f"I couldn't complete reasoning ({budget_exhausted_label}) "
                        "and the fallback synthesiser also failed. Partial findings: "
                        f"{len(ctx.accumulated_hits)} chunks, {len(ctx.sql_calls)} sql calls."
                    ),
                    citations=[],
                    cited_sources=[],
                )
            # reasoning_trace is not reconstructable on the budget-exhausted
            # path — pydantic-ai has no result.all_messages() to translate when
            # the run was cancelled mid-flight. Telemetry + the warning log
            # carry the diagnostic instead.
            return fallback

        # Happy path.
        assert result is not None  # narrowing for type-checker
        answer: Answer = result.output
        answer.cited_sources = _build_cited_sources(
            answer.citations,
            list(ctx.accumulated_hits.values()),
        )
        if include_trace:
            answer.reasoning_trace = _trace_from_messages(result.all_messages(), pattern_name="reasoning_answerer")
        outcome_label = "no_info" if not answer.cited_sources and not ctx.sql_calls else "answered"
        reasoning_terminal_state.add(1, {"outcome": outcome_label})
        return answer
