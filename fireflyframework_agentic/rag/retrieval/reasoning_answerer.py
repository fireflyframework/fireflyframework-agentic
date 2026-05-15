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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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


def _build_knowledge_search():
    """Return an async ``knowledge_search(query, top_k=5)`` closure.

    Closes over the contextvar — callers must :meth:`answer` first. Side-effect:
    every returned :class:`ChunkHit` is recorded in
    ``ctx.accumulated_hits[chunk_id]`` so the orchestrator can enrich
    ``Answer.cited_sources`` post-hoc.
    """
    from typing import Any

    async def knowledge_search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "knowledge_search called outside answer()"
        assert ctx.corpus_agent is not None
        hits = await ctx.corpus_agent.retrieve(query, top_k=top_k, rerank=True)
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
    from typing import Any

    async def sql_query(question: str) -> dict[str, Any]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "sql_query called outside answer()"
        assert ctx.structured_retriever is not None
        outcome = await ctx.structured_retriever.retrieve(question, ctx.schemas)
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
    from typing import Literal

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
        return await inspect_fn(table, column, op, value)

    return inspect_table


def _build_python_compute_tool():
    """Return an async ``python_compute(source, data=None)`` closure.

    Runs the sandbox in the event loop's default executor so the worker thread
    inside :func:`run_python_compute` doesn't block other tool calls.
    """
    import asyncio as _asyncio
    from typing import Any

    from fireflyframework_agentic.rag.retrieval._python_compute import run_python_compute

    async def python_compute(source: str, data: dict[str, Any] | None = None) -> str:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "python_compute called outside answer()"
        loop = _asyncio.get_running_loop()
        return await loop.run_in_executor(None, run_python_compute, source, data)

    return python_compute
