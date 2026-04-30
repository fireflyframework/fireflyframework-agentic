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

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_agentic.rag.retrieval.expander import ExpandedQuery, QueryExpander


def _stub_run_result(variants: list[str], hyde: str = "") -> Any:
    """Builds an object shaped like pydantic_ai's RunResult (.output attribute)."""

    class _Output:
        def __init__(self, vs: list[str], h: str) -> None:
            self.variants = vs
            self.hyde = h

    class _R:
        pass

    r = _R()
    r.output = _Output(variants, hyde)
    return r


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_returns_original_first_then_variants(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(
        return_value=_stub_run_result(
            ["who runs OpenAI", "who is OpenAI's chief executive", "OpenAI leadership"],
        ),
    )
    out = await expander.expand("Who is the CEO of OpenAI?", n_variants=4)
    assert out[0] == ExpandedQuery(text="Who is the CEO of OpenAI?", route="hybrid")
    assert any(q.text == "who runs OpenAI" for q in out)
    assert all(isinstance(q, ExpandedQuery) for q in out)


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_original_is_always_hybrid(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(return_value=_stub_run_result([]))
    out = await expander.expand("Q?")
    assert out[0].route == "hybrid"


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_hyde_has_vec_only_route(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(
        return_value=_stub_run_result(
            ["alternative phrasing"],
            hyde="The CEO is Jane Doe, who founded the company in 2010.",
        ),
    )
    out = await expander.expand("Who is the CEO?", n_variants=4)
    hyde_queries = [q for q in out if q.route == "vec_only"]
    assert len(hyde_queries) == 1
    assert "Jane Doe" in hyde_queries[0].text


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_dedupes_when_variant_equals_original(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(
        return_value=_stub_run_result(["What is X?", "Tell me about X", "What is X?"]),
    )
    out = await expander.expand("What is X?", n_variants=4)
    texts = [q.text for q in out]
    assert texts.count("What is X?") == 1
    assert "Tell me about X" in texts


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_caps_paraphrase_variants(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(
        return_value=_stub_run_result(
            ["v1", "v2", "v3", "v4", "v5", "v6"],
            hyde="Hypothetical passage about Q.",
        ),
    )
    out = await expander.expand("Q", n_variants=3)
    hybrid_queries = [q for q in out if q.route == "hybrid"]
    # original + at most n_variants-1=2 paraphrase variants
    assert len(hybrid_queries) <= 3  # original + 2 paraphrases
    # HyDE appended
    assert any(q.route == "vec_only" for q in out)


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_falls_back_to_original_on_llm_error(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    out = await expander.expand("Q", n_variants=3)
    assert len(out) == 1
    assert out[0].text == "Q"
    assert out[0].route == "hybrid"


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_drops_empty_strings_from_variants(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(
        return_value=_stub_run_result(["", "alt phrasing", "", "another"]),
    )
    out = await expander.expand("orig", n_variants=4)
    assert not any(q.text == "" for q in out)
    assert any(q.text == "alt phrasing" for q in out)
    assert out[0].text == "orig"


@patch("fireflyframework_agentic.rag.retrieval.expander.FireflyAgent")
async def test_expand_logs_each_generated_query(mock_agent_cls, caplog):
    """The expander should log every query (original, variants, hyde) at INFO."""
    import logging

    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(
        return_value=_stub_run_result(
            ["alt one"],
            hyde="Hypothetical document passage.",
        ),
    )

    with caplog.at_level(logging.INFO, logger="fireflyframework_agentic.rag.retrieval.expander"):
        out = await expander.expand("original question", n_variants=3)

    texts = [q.text for q in out]
    assert "original question" in texts
    assert "alt one" in texts
    assert any(q.route == "vec_only" for q in out)

    messages = [r.getMessage() for r in caplog.records]
    assert any("original" in m and "original question" in m for m in messages)
    assert any("variant" in m and "alt one" in m for m in messages)
    assert any("hyde" in m for m in messages)
