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

"""Tests for ``HaikuReranker`` — listwise relevance reranker.

Uses a stubbed FireflyAgent to drive the reranker without making real
LLM calls. Covers:
- LLM returns top-K chunk_ids -> reranker resolves them back to ChunkHits
  in the LLM's order.
- Hallucinated chunk_ids (LLM returns ids not in the input) are dropped.
- Repeated chunk_ids in the LLM output are deduplicated.
- LLM error -> graceful fallback to ``hits[:top_k]`` (retrieval order).
- Short-circuits without an LLM call when:
    - ``hits`` is empty
    - ``top_k <= 0``
    - ``top_k >= len(hits)`` (no rerank needed)
- Logs the kept chunk_ids at INFO for visibility.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from examples.corpus_search.corpus import ChunkHit
from examples.corpus_search.retrieval.reranker import (
    HaikuReranker,
    RerankerResult,
)


def _hit(chunk_id: str, content: str = "", source: str = "/tmp/x.md") -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        score=0.0,
        content=content or f"chunk {chunk_id}",
        source_path=source,
    )


def _stub_run_result(top_chunk_ids: list[str]) -> Any:
    """Builds an object shaped like pydantic_ai's RunResult (.output attr)."""

    class _R:
        pass

    r = _R()
    r.output = RerankerResult(top_chunk_ids=top_chunk_ids)
    return r


# --- Happy paths --------------------------------------------------------


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_rerank_returns_llms_top_k_in_order(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-3", "c-1"]),
    )
    hits = [_hit(f"c-{i}") for i in range(5)]

    out = await reranker.rerank("Q", hits, top_k=2)
    assert [h.chunk_id for h in out] == ["c-3", "c-1"]


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_rerank_drops_hallucinated_chunk_ids(mock_agent_cls):
    """LLM returns chunk_ids that don't appear in the input — drop them.

    Use ``top_k < len(hits)`` so we don't hit the no-rerank short-circuit.
    """
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-2", "fake-id", "c-0", "another-fake"]),
    )
    hits = [_hit(f"c-{i}") for i in range(5)]
    out = await reranker.rerank("Q", hits, top_k=3)

    # Only the two real ids survive
    assert [h.chunk_id for h in out] == ["c-2", "c-0"]


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_rerank_dedupes_repeated_chunk_ids(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-1", "c-1", "c-1"]),
    )
    hits = [_hit(f"c-{i}") for i in range(5)]
    out = await reranker.rerank("Q", hits, top_k=3)

    assert [h.chunk_id for h in out] == ["c-1"]


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_rerank_caps_at_top_k_even_if_llm_returns_more(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-0", "c-1", "c-2", "c-3", "c-4"]),
    )
    hits = [_hit(f"c-{i}") for i in range(5)]
    out = await reranker.rerank("Q", hits, top_k=2)

    assert [h.chunk_id for h in out] == ["c-0", "c-1"]


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_rerank_returns_fewer_than_top_k_when_llm_says_so(mock_agent_cls):
    """LLM is allowed to return fewer ids than requested when only some
    chunks are actually relevant. The reranker trusts that judgment.

    Use ``top_k < len(hits)`` so we don't hit the no-rerank short-circuit.
    """
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-1"]),  # only one actually relevant
    )
    hits = [_hit(f"c-{i}") for i in range(10)]
    out = await reranker.rerank("Q", hits, top_k=5)

    assert [h.chunk_id for h in out] == ["c-1"]


# --- Short-circuits (no LLM call) --------------------------------------


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_empty_hits_returns_empty_without_llm_call(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock()  # would error if called
    out = await reranker.rerank("Q", [], top_k=5)

    assert out == []
    reranker._agent.run.assert_not_awaited()


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_top_k_zero_returns_empty_without_llm_call(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock()
    hits = [_hit(f"c-{i}") for i in range(5)]
    out = await reranker.rerank("Q", hits, top_k=0)

    assert out == []
    reranker._agent.run.assert_not_awaited()


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_top_k_geq_len_hits_returns_hits_without_llm_call(mock_agent_cls):
    """When the user asks for at least as many chunks as we have
    candidates, there's nothing to rerank away — skip the LLM.
    """
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock()
    hits = [_hit("a"), _hit("b"), _hit("c")]

    out_eq = await reranker.rerank("Q", hits, top_k=3)
    out_gt = await reranker.rerank("Q", hits, top_k=10)

    assert [h.chunk_id for h in out_eq] == ["a", "b", "c"]
    assert [h.chunk_id for h in out_gt] == ["a", "b", "c"]
    reranker._agent.run.assert_not_awaited()


# --- Failure paths ------------------------------------------------------


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_llm_error_falls_back_to_retrieval_order(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        side_effect=RuntimeError("LLM unavailable"),
    )
    hits = [_hit(f"c-{i}") for i in range(5)]
    out = await reranker.rerank("Q", hits, top_k=3)

    # Falls back to the first top_k hits in the input order
    assert [h.chunk_id for h in out] == ["c-0", "c-1", "c-2"]


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_llm_returns_empty_list_returns_empty(mock_agent_cls):
    """LLM ran successfully but found nothing relevant. Trust it — empty
    is the right answer (downstream answerer will return 'no info').
    """
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result([]),
    )
    hits = [_hit(f"c-{i}") for i in range(5)]
    out = await reranker.rerank("Q", hits, top_k=3)

    assert out == []


# --- Visibility logging -------------------------------------------------


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_rerank_logs_kept_chunks(mock_agent_cls, caplog):
    """Reranker should log the kept chunk_ids + source_paths at INFO
    so users can see which candidates survived and which were dropped.
    """
    import logging

    mock_agent = MagicMock()
    mock_agent.name = "reranker"  # used in the log message
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-2", "c-0"]),
    )
    hits = [
        _hit("c-0", source="/tmp/A.pdf"),
        _hit("c-1", source="/tmp/B.pdf"),
        _hit("c-2", source="/tmp/A.pdf"),
        _hit("c-3", source="/tmp/B.pdf"),
    ]

    with caplog.at_level(logging.INFO, logger="examples.corpus_search.retrieval.reranker"):
        await reranker.rerank("Q", hits, top_k=2)

    messages = [r.getMessage() for r in caplog.records]
    # Header line with counts
    assert any("4 candidates -> 2 kept" in m for m in messages)
    # Each kept chunk logged with its source path
    assert any("c-2" in m and "/tmp/A.pdf" in m for m in messages)
    assert any("c-0" in m and "/tmp/A.pdf" in m for m in messages)


# --- Constructor sanity -------------------------------------------------


@patch("examples.corpus_search.retrieval.reranker.FireflyAgent")
async def test_passes_question_and_top_k_into_prompt(mock_agent_cls):
    """The LLM prompt should mention the question and the requested top_k."""
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    reranker = HaikuReranker(model="anthropic:dummy")
    reranker._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["c-0"]),
    )
    hits = [_hit("c-0", content="some content")]
    await reranker.rerank("My question", hits + [_hit("c-1"), _hit("c-2")], top_k=2)

    args, _ = reranker._agent.run.call_args
    prompt = args[0]
    assert "My question" in prompt
    assert "top 2" in prompt
    # Each candidate id appears in the formatted block
    assert "[c-0]" in prompt
    assert "[c-1]" in prompt
    assert "[c-2]" in prompt
