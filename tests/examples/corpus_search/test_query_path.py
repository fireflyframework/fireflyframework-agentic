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

"""End-to-end and integration tests for the query path.

Covers the bug surfaced in the smoke test: a natural-language question
containing ``?`` raised ``sqlite3.OperationalError: fts5: syntax error``
inside ``bm25_search``, which silently turned the hybrid retrieval into
vector-only. ``sanitize_fts_query`` now cleans the input before
``MATCH``; these tests prove the sanitisation works and the full query
path returns results for realistic NL questions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from examples.corpus_search.agent import CorpusAgent
from examples.corpus_search.retrieval.answerer import Answer
from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.corpus import (
    SqliteCorpus,
    StoredChunk,
    sanitize_fts_query,
)

# --- sanitize_fts_query unit tests --------------------------------------


class TestSanitizeFtsQuery:
    def test_strips_question_mark(self):
        out = sanitize_fts_query("What is the best region?")
        # No question mark survives
        assert "?" not in out
        # Words are preserved
        assert "best" in out
        assert "region" in out

    def test_strips_double_quotes(self):
        out = sanitize_fts_query('the "best" region')
        # Inner-quote chars stripped; words wrapped in our quoting are intact
        assert '"best"' in out  # our quoting around the bare word
        assert "best" in out

    def test_strips_parens(self):
        out = sanitize_fts_query("(sales) report")
        assert "(" not in out
        assert ")" not in out
        assert "sales" in out
        assert "report" in out

    def test_strips_colons_and_stars(self):
        out = sanitize_fts_query("col:value sales*")
        assert ":" not in out
        assert "*" not in out
        assert "col" in out
        assert "value" in out
        assert "sales" in out

    def test_handles_hyphenated_tokens(self):
        out = sanitize_fts_query("co-founder of OpenAI")
        # Hyphen treated as separator; words preserved
        assert "co" in out
        assert "founder" in out
        assert "OpenAI" in out

    def test_or_join_between_tokens(self):
        out = sanitize_fts_query("alpha beta gamma")
        # Tokens joined with OR for hybrid recall
        assert " OR " in out

    def test_each_token_quoted(self):
        out = sanitize_fts_query("alpha beta")
        # Each token wrapped in double quotes — defensive against
        # accidental FTS5 keyword collisions ("OR", "AND", "NOT")
        assert '"alpha"' in out
        assert '"beta"' in out

    def test_empty_string_returns_empty(self):
        assert sanitize_fts_query("") == ""

    def test_only_special_chars_returns_empty(self):
        assert sanitize_fts_query("?!.,;:") == ""

    def test_unicode_letters_preserved(self):
        # Spanish characters survive (the Brazilian healthcare corpus has
        # plenty of these).
        out = sanitize_fts_query("epidemiología y oncología")
        assert "epidemiología" in out
        assert "oncología" in out

    def test_only_whitespace_returns_empty(self):
        assert sanitize_fts_query("   \t\n  ") == ""

    def test_mixed_special_chars_and_words(self):
        out = sanitize_fts_query("Q: What's the ROI? (2024)")
        # Apostrophe in "What's" splits it — acceptable
        assert "What" in out
        assert "ROI" in out
        assert "2024" in out
        assert "?" not in out
        assert "(" not in out


# --- bm25_search integration with NL queries ----------------------------


@pytest.fixture
async def populated_corpus(tmp_path):
    """A corpus with a few realistic chunks to search across."""
    corpus = SqliteCorpus(tmp_path / "corpus.sqlite")
    await corpus.initialise()
    chunks = [
        StoredChunk(
            chunk_id="d1-0",
            doc_id="d1",
            source_path="/tmp/sales.md",
            index_in_doc=0,
            content="The best region for sales is the Pacific Northwest.",
            metadata={},
        ),
        StoredChunk(
            chunk_id="d1-1",
            doc_id="d1",
            source_path="/tmp/sales.md",
            index_in_doc=1,
            content="Quarterly revenue grew 15% across all regions.",
            metadata={},
        ),
        StoredChunk(
            chunk_id="d2-0",
            doc_id="d2",
            source_path="/tmp/people.md",
            index_in_doc=0,
            content="Sam Altman is the chief executive officer of OpenAI.",
            metadata={},
        ),
    ]
    await corpus.upsert_chunks(chunks)
    yield corpus
    await corpus.close()


async def test_bm25_search_with_question_mark_returns_results(populated_corpus):
    """The original smoke-test bug: ``?`` raised OperationalError. Sanitisation now strips it."""
    hits = await populated_corpus.bm25_search(
        "What is the best region in terms of sales?",
        top_k=10,
    )
    chunk_ids = {h.chunk_id for h in hits}
    # The sales-related chunk is hit
    assert "d1-0" in chunk_ids


async def test_bm25_search_with_quotes_does_not_error(populated_corpus):
    hits = await populated_corpus.bm25_search('Who is the "CEO" of OpenAI?', top_k=10)
    chunk_ids = {h.chunk_id for h in hits}
    assert "d2-0" in chunk_ids


async def test_bm25_search_with_parentheses_does_not_error(populated_corpus):
    hits = await populated_corpus.bm25_search("(sales report) Q4", top_k=10)
    # Should at least not raise; may or may not hit depending on tokenizer
    assert isinstance(hits, list)


async def test_bm25_search_with_colon_and_star_does_not_error(populated_corpus):
    hits = await populated_corpus.bm25_search("col:value sales*", top_k=10)
    chunk_ids = {h.chunk_id for h in hits}
    # "sales" is in d1-0 and d1-1
    assert {"d1-0", "d1-1"} & chunk_ids


async def test_bm25_search_with_only_punctuation_returns_empty(populated_corpus):
    hits = await populated_corpus.bm25_search("?!.,;:", top_k=10)
    assert hits == []


async def test_bm25_search_with_empty_query_returns_empty(populated_corpus):
    hits = await populated_corpus.bm25_search("", top_k=10)
    assert hits == []


async def test_bm25_search_or_semantics_recalls_any_matching_word(populated_corpus):
    """OR-tokenised match: "sales OR moonbase" should still hit sales-containing chunks."""
    hits = await populated_corpus.bm25_search("sales moonbase", top_k=10)
    chunk_ids = {h.chunk_id for h in hits}
    assert "d1-0" in chunk_ids or "d1-1" in chunk_ids


# --- End-to-end query path with stub LLMs -------------------------------


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
            self.docs[d.id] = {"embedding": d.embedding, "text": d.text, "metadata": d.metadata}

    async def delete(self, ids: Sequence[str], namespace: str = "default") -> None:
        for i in ids:
            self.docs.pop(i, None)

    async def search(
        self, query_embedding: list[float], top_k: int = 5, namespace: str = "default", filters: Any = None
    ) -> list[Any]:
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


@pytest.fixture
async def agent(tmp_path):
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
            _embedder=_StubEmbedder(),
            _vector_store=_StubVectorStore(),
        )
        await a._ensure_started()

        # Default the reranker to a passthrough so query-path tests focus
        # on the surrounding pipeline. Individual tests override when they
        # want to exercise reranker semantics.
        async def _passthrough(question, hits, *, top_k):
            return list(hits[:top_k])

        a._reranker.rerank = _passthrough
    yield a
    await a.close()


def _stub_run_result(answer: Answer) -> Any:
    class _R:
        pass

    r = _R()
    r.output = answer
    return r


async def test_query_with_question_mark_does_not_blow_up_bm25(agent, tmp_path):
    """The original bug: ``?`` made BM25 return [] for every reformulation,
    leaving only vector hits. With sanitisation in place, BM25 contributes
    real hits even for question-mark-terminated NL questions.
    """
    src = tmp_path / "drop"
    src.mkdir()
    (src / "doc.txt").write_text("The best sales region is the Pacific Northwest. Revenue is up.")
    await agent.ingest_one(src / "doc.txt")

    # Stub expansion and answer.
    agent._expander.expand = AsyncMock(
        return_value=[
            "What is the best region in terms of sales?",
            "best sales region",
        ]
    )
    canned = Answer(text="Pacific Northwest [d-0].", citations=["d-0"])
    agent._answerer._agent.run = AsyncMock(return_value=_stub_run_result(canned))

    # Run BM25 directly first to confirm sanitisation made it work.
    bm25_hits = await agent._corpus.bm25_search(
        "What is the best region in terms of sales?",
        top_k=10,
    )
    assert len(bm25_hits) >= 1, "sanitisation should let BM25 return hits for ?-terminated queries"

    # Now full query path
    result = await agent.query("What is the best region in terms of sales?")
    assert result.text == canned.text
    assert result.citations == ["d-0"]


async def test_query_with_punctuation_only_question_returns_no_info(agent):
    """If the user submits just punctuation, expansion may produce empty
    variants. Retrieval returns no hits; answerer returns the canned
    no-info string without calling the LLM.
    """
    agent._expander.expand = AsyncMock(return_value=["???"])
    agent._answerer._agent.run = AsyncMock()  # would error if called
    result = await agent.query("???")
    assert result.text == "I don't have enough information."
    agent._answerer._agent.run.assert_not_awaited()


async def test_query_routes_top_k_to_reranker_not_retriever(agent, tmp_path):
    """``query(top_k=N)`` is the *post-rerank* count: retriever pulls the
    wider ``rerank_pool`` (default 20), then the reranker narrows to ``N``.
    """
    src = tmp_path / "drop"
    src.mkdir()
    for i in range(5):
        (src / f"doc{i}.txt").write_text(f"document {i} sales report")
        await agent.ingest_one(src / f"doc{i}.txt")

    agent._expander.expand = AsyncMock(return_value=["sales"])
    canned = Answer(text="ok", citations=[])
    agent._answerer._agent.run = AsyncMock(return_value=_stub_run_result(canned))

    # Spy on retriever — should see the rerank_pool, not the user's top_k.
    original_retrieve = agent._retriever.retrieve
    seen_retrieve_top_k: list[int] = []

    async def _retrieve_spy(queries, *, top_k_per_query, top_k_final):
        seen_retrieve_top_k.append(top_k_final)
        return await original_retrieve(queries, top_k_per_query=top_k_per_query, top_k_final=top_k_final)

    agent._retriever.retrieve = _retrieve_spy

    # Spy on reranker — should see the user's top_k.
    seen_rerank_top_k: list[int] = []

    async def _rerank_spy(question, hits, *, top_k):
        seen_rerank_top_k.append(top_k)
        return list(hits[:top_k])

    agent._reranker.rerank = _rerank_spy

    await agent.query("sales", top_k=3)

    assert seen_retrieve_top_k == [agent._rerank_pool]  # default 20
    assert seen_rerank_top_k == [3]


async def test_query_with_unicode_question_does_not_blow_up(agent, tmp_path):
    """Spanish/Portuguese accents are preserved through sanitisation."""
    src = tmp_path / "drop"
    src.mkdir()
    (src / "saude.txt").write_text("El sistema de saúde brasileño tiene grandes retos en oncología y epidemiología.")
    await agent.ingest_one(src / "saude.txt")

    agent._expander.expand = AsyncMock(return_value=["¿Qué retos tiene la oncología en Brasil?"])
    canned = Answer(text="Retos de oncología [d-0].", citations=["d-0"])
    agent._answerer._agent.run = AsyncMock(return_value=_stub_run_result(canned))

    # BM25 should hit thanks to unicode-aware sanitisation
    bm25_hits = await agent._corpus.bm25_search("¿Qué retos tiene la oncología?", top_k=10)
    assert len(bm25_hits) >= 1

    result = await agent.query("¿Qué retos tiene la oncología en Brasil?")
    assert result.text == canned.text
