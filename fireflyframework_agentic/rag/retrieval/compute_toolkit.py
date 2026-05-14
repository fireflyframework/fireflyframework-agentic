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

"""Corpus-bound deterministic executors for the compute stage.

Each public dispatch returns a :class:`ComputeObservation` capturing the
inputs (via the step model on the trace), the structured output, and the
citations that ground the result.  No executor here calls an LLM.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fireflyframework_agentic.rag.corpus import ChunkHit

# `_connect` is shared with the SQL retriever to keep UDF registration in
# one place; it stays private to ``rag/retrieval/`` and is not re-exported.
from fireflyframework_agentic.rag.retrieval.sql import (
    SqlRetrievalOutcome,
    TargetSchema,
    _connect,
)
from fireflyframework_agentic.reasoning.compute_steps import (
    ComputeObservation,
    ComputeStep,
    SqlRunStep,
    StepRef,
)


@dataclass(slots=True)
class RetrievalContext:
    """Inputs the toolkit needs from the prior retrieval stage."""

    top_hits: Sequence[ChunkHit] = field(default_factory=list)
    sql_outcome: SqlRetrievalOutcome | None = None
    schemas: list[TargetSchema] = field(default_factory=list)


# Word boundaries (\b...\b) match the verb only as a standalone token.
# Names like ``updates``, ``update_count``, ``dropdowns``, or
# ``attachments`` are correctly NOT rejected. Only bare verb tokens
# (e.g. ``UPDATE``, ``DROP``) get matched.
_WRITE_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)


class ComputeToolkit:
    """Deterministic executors for the corpus compute stage."""

    def __init__(self, *, corpus_db_path: Path, retrieval_context: RetrievalContext) -> None:
        self._db_path = corpus_db_path
        self._ctx = retrieval_context

    async def dispatch(
        self,
        step: ComputeStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        """Execute one typed step and return its observation.

        Dispatch is by ``step.kind``.  Each executor is responsible for
        catching its own exceptions and returning a failed observation
        with a meaningful ``error`` message.
        """
        try:
            if isinstance(step, SqlRunStep):
                return await self._run_sql(step, previous)
            return ComputeObservation(
                step_id=step.id,
                success=False,
                output=None,
                error=f"unsupported step kind: {step.kind}",
            )
        except Exception as exc:  # noqa: BLE001 — observations encapsulate failure
            return ComputeObservation(
                step_id=step.id,
                success=False,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _run_sql(
        self,
        step: SqlRunStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        if _WRITE_SQL.search(step.sql):
            return ComputeObservation(
                step_id=step.id, success=False, error="sql is not read-only (only SELECT is allowed)"
            )
        params = _resolve_params(step.params, previous)
        if isinstance(params, str):  # error message
            return ComputeObservation(step_id=step.id, success=False, error=params)

        conn = _connect(self._db_path)
        try:
            cursor = conn.execute(step.sql, params)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]
        finally:
            conn.close()
        return ComputeObservation(
            step_id=step.id,
            success=True,
            output={"columns": columns, "rows": rows, "sql": step.sql},
        )


def _resolve_params(
    raw: dict[str, Any],
    previous: dict[str, ComputeObservation],
) -> dict[str, Any] | str:
    """Resolve StepRef placeholders against prior observations.

    Returns either the resolved dict or an error string explaining what
    could not be resolved.  Path syntax is intentionally minimal: dotted
    keys plus ``[N]`` indices and ``[*]`` for whole list extraction.
    """
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, StepRef):
            if value.step_id not in previous:
                return f"step '{value.step_id}' not found in prior observations"
            obs = previous[value.step_id]
            if not obs.success:
                return f"step '{value.step_id}' did not succeed; cannot reference it"
            try:
                resolved = _apply_path(obs.output, value.path) if value.path else obs.output
            except (KeyError, IndexError, AttributeError, ValueError, TypeError) as exc:
                return f"path '{value.path}' on step '{value.step_id}' failed: {type(exc).__name__}: {exc}"
            if isinstance(resolved, list) and len(resolved) == 1:
                resolved = resolved[0]
            out[key] = resolved
        else:
            out[key] = value
    return out


def _apply_path(data: Any, path: str) -> Any:
    """Tiny JSONPath-ish accessor: ``$.foo.bar[0]``, ``$.rows[*].id``."""
    if not path or path == "$":
        return data
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\[\d+\]|\[\*\]", path)
    current: Any = data
    projecting = False
    for tok in tokens:
        if tok == "[*]":
            if not isinstance(current, list):
                raise ValueError(f"[*] requires a list, got {type(current).__name__}")
            projecting = True
            # current stays as the list; subsequent accesses map over it
        elif tok.startswith("[") and tok.endswith("]"):
            idx = int(tok[1:-1])
            current = [c[idx] for c in current] if projecting else current[idx]
        else:
            current = (
                [c[tok] if isinstance(c, dict) else getattr(c, tok) for c in current]
                if projecting
                else current[tok]
                if isinstance(current, dict)
                else getattr(current, tok)
            )
    return current
