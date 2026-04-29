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

from examples.corpus_search.retrieval.expander import QueryExpander


def _stub_run_result(variants: list[str]) -> Any:
    """Builds an object shaped like pydantic_ai's RunResult (.output attribute)."""

    class _Output:
        def __init__(self, vs: list[str]) -> None:
            self.variants = vs

    class _R:
        pass

    r = _R()
    r.output = _Output(variants)
    return r


@patch("examples.corpus_search.retrieval.expander.FireflyAgent")
async def test_expand_returns_original_first_then_variants(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(
            ["who runs OpenAI", "who is OpenAI's chief executive", "OpenAI leadership"],
        ),
    )
    out = await expander.expand("Who is the CEO of OpenAI?", n_variants=3)
    assert out[0] == "Who is the CEO of OpenAI?"
    assert "who runs OpenAI" in out
    assert len(out) <= 4  # original + n_variants


@patch("examples.corpus_search.retrieval.expander.FireflyAgent")
async def test_expand_dedupes_when_variant_equals_original(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["What is X?", "Tell me about X", "What is X?"]),
    )
    out = await expander.expand("What is X?", n_variants=3)
    assert out.count("What is X?") == 1
    assert "Tell me about X" in out


@patch("examples.corpus_search.retrieval.expander.FireflyAgent")
async def test_expand_caps_at_n_variants_plus_one(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["v1", "v2", "v3", "v4", "v5", "v6"]),
    )
    out = await expander.expand("Q", n_variants=3)
    assert len(out) == 4  # original + at most 3 variants


@patch("examples.corpus_search.retrieval.expander.FireflyAgent")
async def test_expand_falls_back_to_original_on_llm_error(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(  # type: ignore[attr-defined]
        side_effect=RuntimeError("LLM unavailable"),
    )
    out = await expander.expand("Q", n_variants=3)
    assert out == ["Q"]


@patch("examples.corpus_search.retrieval.expander.FireflyAgent")
async def test_expand_drops_empty_strings_from_variants(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["", "alt phrasing", "", "another"]),
    )
    out = await expander.expand("orig", n_variants=3)
    assert "" not in out
    assert "alt phrasing" in out
    assert out[0] == "orig"


@patch("examples.corpus_search.retrieval.expander.FireflyAgent")
async def test_expand_logs_each_generated_query(mock_agent_cls, caplog):
    """For visibility — the expander should log every query (original +
    variants) at INFO so the user sees what BM25 + vector search will run.
    """
    import logging

    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    expander = QueryExpander(model="anthropic:dummy")
    expander._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(["alt one", "alt two"]),
    )

    with caplog.at_level(logging.INFO, logger="examples.corpus_search.retrieval.expander"):
        out = await expander.expand("original question", n_variants=2)

    assert out == ["original question", "alt one", "alt two"]
    messages = [r.getMessage() for r in caplog.records]
    # Header line with count
    assert any("produced 3 query" in m for m in messages)
    # Original labelled
    assert any("original" in m and "original question" in m for m in messages)
    # Variants labelled
    assert any("variant 1" in m and "alt one" in m for m in messages)
    assert any("variant 2" in m and "alt two" in m for m in messages)
