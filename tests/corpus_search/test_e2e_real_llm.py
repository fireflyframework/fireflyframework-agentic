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

"""End-to-end test against real Anthropic + OpenAI APIs.

Skipped automatically unless both ANTHROPIC_API_KEY and OPENAI_API_KEY are set.
Run with: ANTHROPIC_API_KEY=... OPENAI_API_KEY=... uv run pytest tests/corpus_search/test_e2e_real_llm.py -v
"""

from __future__ import annotations

import os

import pytest

from examples.corpus_search.agent import CorpusAgent

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("OPENAI_API_KEY")),
    reason="Real LLM keys not present (need ANTHROPIC_API_KEY + OPENAI_API_KEY).",
)


async def test_ingest_then_query_with_real_llms(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "company.md").write_text(
        "# Company Notes\n\n"
        "Sam Altman is the chief executive officer of OpenAI.\n"
        "Greg Brockman serves as President of OpenAI.\n\n"
        "## Approval workflow\n\n"
        "Submit request -> manager review -> approval -> end.\n"
    )

    agent = CorpusAgent(
        root=tmp_path / "kg",
        embed_model="openai:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
    )
    try:
        results = await agent.ingest_folder(drop)
        assert len(results) == 1
        assert results[0].status == "success"
        assert results[0].n_chunks >= 1

        answer = await agent.query("Who is the CEO of OpenAI?")
        # Answer should mention Altman and have at least one citation.
        assert "Altman" in answer.text
        assert len(answer.citations) >= 1
    finally:
        await agent.close()


async def test_ingest_skips_unchanged_file_on_second_run(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "stable.md").write_text("Some stable content that won't change.")

    agent = CorpusAgent(
        root=tmp_path / "kg",
        embed_model="openai:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
    )
    try:
        first = await agent.ingest_folder(drop)
        assert first[0].status == "success"
        second = await agent.ingest_folder(drop)
        assert second[0].status == "skipped"
    finally:
        await agent.close()
