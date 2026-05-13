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

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.answerer import (
    _INSTRUCTIONS,
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


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
async def test_empty_hits_returns_no_info_without_llm_call(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    answerer._agent.run = AsyncMock()  # type: ignore[attr-defined]
    result = await answerer.answer("Q", [])
    assert result.text == "I don't have enough information."
    assert result.citations == []
    answerer._agent.run.assert_not_awaited()


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
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


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
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


# --- cited_sources enrichment ----------------------------------------------


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
async def test_cited_sources_enriched_from_hits(mock_agent_cls):
    """The LLM returns chunk_id citations; the agent should enrich them
    into CitedSource records with source_path + snippet pulled from the
    hits we passed in.
    """
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    canned = Answer(
        text="The regulator's resolution establishes [d-3] and updates rules [d-9].",
        citations=["d-3", "d-9"],
    )
    answerer._agent.run = AsyncMock(return_value=_stub_run_result(canned))

    hits = [
        _hit("d-3", "Source chunk text describing the new procedure.", source="/tmp/regulation.pdf"),
        _hit("d-9", "Source chunk text describing the rule update.", source="/tmp/regulation.pdf"),
        _hit("d-99", "Unrelated chunk that wasn't cited.", source="/tmp/other.pdf"),
    ]
    result = await answerer.answer("What does the regulation establish?", hits)

    assert {s.chunk_id for s in result.cited_sources} == {"d-3", "d-9"}
    by_id = {s.chunk_id: s for s in result.cited_sources}
    assert by_id["d-3"].source_path == "/tmp/regulation.pdf"
    assert by_id["d-3"].snippet.startswith("Source chunk text")
    assert by_id["d-9"].source_path == "/tmp/regulation.pdf"


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
async def test_cited_sources_drops_hallucinated_chunk_ids(mock_agent_cls):
    """If the LLM cites a chunk_id that wasn't in the hits, drop it from
    cited_sources rather than fabricating a record.
    """
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    canned = Answer(
        text="real claim [a-0]; fake claim [made-up-id].",
        citations=["a-0", "made-up-id"],
    )
    answerer._agent.run = AsyncMock(return_value=_stub_run_result(canned))

    hits = [_hit("a-0", "Real chunk content.")]
    result = await answerer.answer("Q", hits)

    assert [s.chunk_id for s in result.cited_sources] == ["a-0"]


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
async def test_cited_sources_dedupes_repeated_citations(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    canned = Answer(
        text="claim [a-0] more claim [a-0] yet another [a-0]",
        citations=["a-0", "a-0", "a-0"],
    )
    answerer._agent.run = AsyncMock(return_value=_stub_run_result(canned))

    hits = [_hit("a-0", "Some content.")]
    result = await answerer.answer("Q", hits)

    assert [s.chunk_id for s in result.cited_sources] == ["a-0"]


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
async def test_empty_hits_returns_no_info_with_empty_cited_sources(mock_agent_cls):
    """No hits -> short-circuit to no-info answer with cited_sources=[]."""
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    answerer = AnswerAgent(model="anthropic:dummy")
    answerer._agent.run = AsyncMock()  # would error if called
    result = await answerer.answer("Q", [])
    assert result.cited_sources == []


# --- diacritic preservation guidance --------------------------------------
#
# Issue #157: the answerer was emitting Spanish prose without diacritical
# marks ('produccion' instead of 'producción'). The fix lives in the
# instruction string passed to the LLM; the tests below lock in that the
# guidance is present in the constant AND reaches the underlying agent at
# construction time, so a future refactor cannot silently drop it.


def test_instructions_pin_answer_in_question_language_rule():
    """Cheap structural assertion against accidental deletion.

    Pinning the literal phrase 'same language as the user' would be
    over-rigid, but the *rule* must remain — search for an unambiguous
    fragment that wouldn't survive a rewrite that removed the policy.
    """
    assert "same language as the user" in _INSTRUCTIONS


def test_instructions_pin_diacritic_preservation_rule():
    """The instructions must tell the model to preserve diacritics.

    We check for the explicit ASCII-vs-accent contrast example
    (``'producción'``/``'produccion'``) — that example is the load-bearing
    illustration of the rule. If it disappears, the rule has been weakened
    or removed.
    """
    assert "producción" in _INSTRUCTIONS
    assert "produccion" in _INSTRUCTIONS
    # And the high-level intent phrase is still there.
    assert "diacritical" in _INSTRUCTIONS.lower()


@patch("fireflyframework_agentic.rag.retrieval.answerer.FireflyAgent")
def test_answer_agent_wires_diacritic_instructions_to_underlying_agent(mock_agent_cls):
    """Construction-time wiring check.

    Loading the constant is one thing; reaching the LLM is another. Verify
    that ``AnswerAgent.__init__`` forwards the instructions verbatim, so a
    future refactor that swaps the instruction source can't silently lose
    the rule between the module-level constant and the runtime prompt.
    """
    AnswerAgent(model="anthropic:dummy")
    assert mock_agent_cls.called
    _, kwargs = mock_agent_cls.call_args
    assert kwargs["instructions"] == _INSTRUCTIONS
    # Belt-and-braces: the wired-in string itself contains the rule.
    assert "diacritical" in kwargs["instructions"].lower()


# --- canonical-name resolution + stale-source warning ---------------------
#
# A real-corpus query ("who reports to <short name>?") returned a list of
# direct reports without indicating which canonical name was matched —
# the user's short input had no exact match in the data, and the SQL agent
# fuzzy-matched it to a longer formal name in a historical snapshot
# sheet. The answer silently used that match without (a) naming the
# canonical entity it picked or (b) flagging that the match came from
# a date-stamped (historical) source. Two pin tests below guard both
# halves of the fix against accidental deletion.


def test_instructions_pin_canonical_name_resolution_rule():
    """The instructions must tell the model to surface which canonical
    value it matched when the user's filter string and the data don't
    match verbatim. Without this, name-based filters silently bridge
    through fuzzy matches the user can't verify.
    """
    # The high-level intent.
    assert "canonical value" in _INSTRUCTIONS
    # The load-bearing worked example (synthetic). If this disappears,
    # the model loses its template for how to phrase the disambiguation.
    assert "Sam Lee" in _INSTRUCTIONS
    assert "SAMUEL ANDREW LEE THOMPSON" in _INSTRUCTIONS
    # Must specify "which source table" so the user can audit the match.
    assert "source table" in _INSTRUCTIONS.lower()


def test_instructions_pin_stale_source_warning_rule():
    """The instructions must tell the model to flag when the matched
    canonical value comes from a historical-looking source (date-shaped
    sheet name like ``_2020``, ``_q1_2024``, ``snapshot_jan_2023``).
    A silent match against an old snapshot is data-correctness
    failure, not just a UX nit — yesterday's manager may not be today's.
    """
    lowered = _INSTRUCTIONS.lower()
    assert "historical" in lowered
    # The concrete sheet-naming patterns the model should look for.
    assert "_2020" in _INSTRUCTIONS
    # And the imperative.
    assert "warn" in lowered or "flag" in lowered
