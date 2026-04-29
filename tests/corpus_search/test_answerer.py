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

from examples.corpus_search.corpus import ChunkHit
from examples.corpus_search.retrieval.answerer import (
    Answer,
    AnswerAgent,
    format_chunks_for_prompt,
)


def _stub_run_result(answer: Answer) -> Any:
    """Builds an object shaped like pydantic_ai's RunResult (.output attribute)."""
    class _R:
        pass
    r = _R()
    r.output = answer
    return r


def _hit(chunk_id: str, content: str, source: str = "/tmp/x.md") -> ChunkHit:
    return ChunkHit(chunk_id=chunk_id, score=0.0, content=content, source_path=source)


def test_format_chunks_includes_id_source_and_content():
    hits = [
        _hit("a-0", "First chunk content.", source="/tmp/a.md"),
        _hit("b-1", "Second chunk content.", source="/tmp/b.md"),
    ]
    formatted = format_chunks_for_prompt(hits)
    assert "[a-0]" in formatted
    assert "[b-1]" in formatted
    assert "/tmp/a.md" in formatted
    assert "First chunk content." in formatted
    assert "Second chunk content." in formatted


def test_format_chunks_empty_returns_empty_string():
    assert format_chunks_for_prompt([]) == ""


@patch("examples.corpus_search.retrieval.answerer.FireflyAgent")
async def test_empty_hits_returns_no_info_without_llm_call(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    answerer._agent.run = AsyncMock()  # type: ignore[attr-defined]
    result = await answerer.answer("Q", [])
    assert result.text == "I don't have enough information."
    assert result.citations == []
    answerer._agent.run.assert_not_awaited()


@patch("examples.corpus_search.retrieval.answerer.FireflyAgent")
async def test_answer_returns_llm_output(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    canned = Answer(
        text="Sam Altman is the CEO of OpenAI [a-0].",
        citations=["a-0"],
    )
    answerer._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(canned),
    )
    hits = [_hit("a-0", "Sam Altman is the CEO of OpenAI.")]
    result = await answerer.answer("Who is the CEO of OpenAI?", hits)
    assert result.text == canned.text
    assert result.citations == ["a-0"]


@patch("examples.corpus_search.retrieval.answerer.FireflyAgent")
async def test_answer_passes_question_and_chunks_to_agent(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    canned = Answer(text="ok", citations=[])
    answerer._agent.run = AsyncMock(  # type: ignore[attr-defined]
        return_value=_stub_run_result(canned),
    )
    hits = [_hit("a-0", "Hello world")]
    await answerer.answer("Question text", hits)
    args, _ = answerer._agent.run.call_args
    assert "Question text" in args[0]
    assert "[a-0]" in args[0]
    assert "Hello world" in args[0]


def test_answer_pydantic_model_validates():
    a = Answer(text="hello", citations=["x", "y"])
    assert a.text == "hello"
    assert a.citations == ["x", "y"]
    # Default citations is empty list
    a2 = Answer(text="hi")
    assert a2.citations == []
