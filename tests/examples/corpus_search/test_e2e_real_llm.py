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

"""End-to-end test against real Anthropic + Azure OpenAI APIs.

Skipped automatically unless ANTHROPIC_API_KEY, EMBEDDING_BINDING_HOST, and
EMBEDDING_BINDING_API_KEY are set — the same secrets the rest of the nightly
RAG suite (test_mcp_corpus_e2e.py, test_full_integration.py, …) uses for the
Azure OpenAI embedding path.

Run locally::

    set -a && . .env && set +a && uv run pytest tests/examples/corpus_search/test_e2e_real_llm.py -v
"""

from __future__ import annotations

import os

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent

_REQUIRED_ENV_VARS = ("ANTHROPIC_API_KEY", "EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY")
_SKIP_REASON = f"Real LLM + embedding keys not present (need {', '.join(_REQUIRED_ENV_VARS)})."


def _real_agent(root):
    return CorpusAgent(
        root=root,
        embed_model="azure:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
    )


@pytest.mark.nightly
@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV_VARS),
    reason=_SKIP_REASON,
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

    agent = _real_agent(tmp_path / "kg")
    try:
        summary = await agent.ingest_folder(drop)
        assert len(summary.results) == 1
        assert summary.results[0].status == "success"
        assert summary.results[0].n_chunks >= 1

        answer = await agent.query("Who is the CEO of OpenAI?")
        # Answer should mention Altman and have at least one citation.
        assert "Altman" in answer.text
        assert len(answer.citations) >= 1
    finally:
        await agent.close()


@pytest.mark.nightly
@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV_VARS),
    reason=_SKIP_REASON,
)
async def test_ingest_skips_unchanged_file_on_second_run(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "stable.md").write_text("Some stable content that won't change.")

    agent = _real_agent(tmp_path / "kg")
    try:
        first = await agent.ingest_folder(drop)
        assert first.results[0].status == "success"
        second = await agent.ingest_folder(drop)
        assert second.results[0].status == "skipped"
    finally:
        await agent.close()
