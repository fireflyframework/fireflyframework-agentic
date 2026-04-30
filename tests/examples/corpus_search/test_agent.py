# Copyright 2026 Firefly Software Solutions Inc
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

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from examples.corpus_search.agent import CorpusAgent
from examples.corpus_search.retrieval.answerer import Answer
from fireflyframework_agentic.embeddings.types import EmbeddingResult

# --- Stubs --------------------------------------------------------------


class _StubEmbedder:
    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[[float(len(t)), 0.0, 0.0, 0.0] for t in texts],
            model="stub",
            usage=None,
            dimensions=4,
        )

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class _StubVectorStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def upsert(self, documents: Sequence[Any], namespace: str = "default") -> None:
        for d in documents:
            # Match the framework's VectorDocument shape — `.text`, not `.content`.
            self.docs[d.id] = {"embedding": d.embedding, "text": d.text, "metadata": d.metadata}

    async def delete(self, ids: Sequence[str], namespace: str = "default") -> None:
        for i in ids:
            self.docs.pop(i, None)

    async def search(
        self, query_embedding: list[float], top_k: int = 5, namespace: str = "default", filters: Any = None
    ) -> list[Any]:
        # Naive: return all known docs ordered by id (deterministic)
        out = []
        for did in sorted(self.docs):

            class _R:
                def __init__(self, i: str) -> None:
                    self.id = i
                    self.score = 0.0
                    self.metadata: dict[str, Any] = {}
                    self.content = ""

            out.append(_R(did))
        return out[:top_k]


# --- Fixtures -----------------------------------------------------------


@pytest.fixture
async def agent(tmp_path):
    """CorpusAgent wired with stub embedder + stub vector store + stub LLM agents."""
    mock_agent_instance = MagicMock()
    with (
        patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent", return_value=mock_agent_instance),
        patch("examples.corpus_search.retrieval.answerer.FireflyAgent", return_value=mock_agent_instance),
        patch("fireflyframework_agentic.rag.retrieval.reranker.FireflyAgent", return_value=mock_agent_instance),
    ):
        a = CorpusAgent(
            root=tmp_path / "kg",
            embed_model="openai:text-embedding-3-small",
            expansion_model="anthropic:dummy",
            answer_model="anthropic:dummy",
            rerank_model="anthropic:dummy",
            rerank_pool=20,
            # Inject stubs to avoid real network calls
            _embedder=_StubEmbedder(),
            _vector_store=_StubVectorStore(),
        )
        # _ensure_started constructs QueryExpander + AnswerAgent + HaikuReranker
        # (lazy); keep the FireflyAgent patches active during this call.
        await a._ensure_started()
    yield a
    await a.close()


# --- Tests --------------------------------------------------------------


async def test_ingest_one_writes_chunks_and_returns_result(agent, tmp_path):
    src = tmp_path / "drop"
    src.mkdir()
    f = src / "doc.txt"
    f.write_text("Hello world. Sam Altman runs OpenAI in San Francisco.")
    result = await agent.ingest_one(f)
    assert result.status == "success"
    assert result.n_chunks >= 1
    rows = await agent._corpus.query("SELECT chunk_id FROM chunks")
    assert len(rows) == result.n_chunks


async def test_ingest_folder_processes_each_file(agent, tmp_path):
    src = tmp_path / "drop"
    src.mkdir()
    (src / "a.txt").write_text("Content for section A with enough text to pass filter.")
    (src / "b.txt").write_text("Content for section B with enough text to pass filter.")
    results = await agent.ingest_folder(src)
    assert len(results) == 2
    assert all(r.status == "success" for r in results)


async def _passthrough_reranker(question, hits, *, top_k):
    """Stub reranker that just keeps the first ``top_k`` hits in input order."""
    return list(hits[:top_k])


async def test_query_returns_answer_with_citations(agent, tmp_path):
    src = tmp_path / "drop"
    src.mkdir()
    f = src / "doc.txt"
    f.write_text("Sam Altman is the CEO of OpenAI based in San Francisco.")
    await agent.ingest_one(f)

    # Stub each stage of the query pipeline to avoid real LLM calls.
    agent._expander.expand = AsyncMock(return_value=["sam altman"])
    agent._reranker.rerank = _passthrough_reranker
    canned = Answer(text="Sam Altman is the CEO. [d-0]", citations=["d-0"])

    class _RR:
        def __init__(self, a: Answer) -> None:
            self.output = a

    agent._answerer._agent.run = AsyncMock(return_value=_RR(canned))

    result = await agent.query("Who is Sam Altman?")
    assert isinstance(result, Answer)
    assert result.text == canned.text
    assert result.citations == ["d-0"]


async def test_query_with_no_corpus_returns_no_info(agent):
    # Don't ingest anything.
    agent._expander.expand = AsyncMock(return_value=["nothing here"])
    agent._reranker.rerank = _passthrough_reranker
    # The answerer agent's .run shouldn't even be called since hits will be empty.
    agent._answerer._agent.run = AsyncMock()  # would error if called
    result = await agent.query("anything?")
    assert result.text == "I don't have enough information."
    assert result.citations == []
    agent._answerer._agent.run.assert_not_awaited()
