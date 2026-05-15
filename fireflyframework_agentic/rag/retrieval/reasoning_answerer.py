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
