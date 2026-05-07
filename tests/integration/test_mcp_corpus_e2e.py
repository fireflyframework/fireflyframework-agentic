# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""End-to-end test of the corpus_rag MCP tools against real LLM + embedding APIs.

Drives the FastMCP server in-memory through ``fastmcp.Client`` to verify the
full MCP wire path: ``list_corpora`` (empty) -> ``ingest_corpus_filesystem``
of the synthetic Acme benchmark corpus -> ``list_corpora`` (one entry) ->
``corpus_query`` returning a grounded answer with citations.

Marked ``@pytest.mark.nightly`` because it spends real Anthropic + Azure
OpenAI quota and takes ~30 s; auto-skips when secrets aren't configured.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastmcp import Client

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.tools.builtins import corpus_rag
from fireflyframework_agentic.tools.registry import ToolRegistry

_BENCH_CORPUS = Path(__file__).resolve().parents[2] / "tests" / "examples" / "corpus_search" / "benchmark" / "corpus"

_REQUIRED_SECRETS = ("EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY", "ANTHROPIC_API_KEY")


def _build_registry() -> ToolRegistry:
    """Build an isolated registry containing only the corpus_rag tools.

    The autouse ``_clear_registries`` fixture wipes the global tool registry
    between tests; the @firefly_tool decorators only run on first import, so
    we register the cached tool instances on a fresh registry instead of
    relying on import-time side effects.
    """
    reg = ToolRegistry()
    for name in (
        "list_corpora",
        "ingest_corpus_filesystem",
        "corpus_retrieve",
        "corpus_query",
    ):
        reg.register(getattr(corpus_rag, name))
    return reg


@pytest.mark.nightly
@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_SECRETS),
    reason=f"Requires {', '.join(_REQUIRED_SECRETS)}",
)
async def test_mcp_list_ingest_query_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "corpora"))
    # Match the embedding path nightly CI provides (EMBEDDING_BINDING_HOST/_API_KEY).
    monkeypatch.setenv("EMBEDDING_MODEL", "azure:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-4-5-20251001")

    app = create_mcp_app(registry=_build_registry())

    async with Client(app) as client:
        names = {t.name for t in await client.list_tools()}
        assert {"list_corpora", "ingest_corpus_filesystem", "corpus_query"} <= names

        empty = (await client.call_tool("list_corpora", {})).data
        assert empty["corpora"] == []

        ingested = (
            await client.call_tool(
                "ingest_corpus_filesystem",
                {"corpus_id": "acme-bench", "root_path": str(_BENCH_CORPUS)},
            )
        ).data
        assert ingested["corpus_id"] == "acme-bench"
        assert ingested["ingested"] >= 12  # 12 markdown docs + spreadsheets
        assert ingested["failed"] == 0

        listed = (await client.call_tool("list_corpora", {})).data
        ids = [c["corpus_id"] for c in listed["corpora"]]
        assert ids == ["acme-bench"]
        assert listed["corpora"][0]["size_bytes"] > 0

        factual = (
            await client.call_tool(
                "corpus_query",
                {
                    "corpus_id": "acme-bench",
                    "question": "Who is the CEO of Acme Corp?",
                    "top_k": 5,
                },
            )
        ).data
        assert "Patel" in factual["answer"]
        assert len(factual["citations"]) >= 1
        assert any("01_company_overview.md" in src["source_path"] for src in factual["cited_sources"])

        negative = (
            await client.call_tool(
                "corpus_query",
                {
                    "corpus_id": "acme-bench",
                    "question": "What is the capital of Mongolia?",
                    "top_k": 5,
                },
            )
        ).data
        # Out-of-corpus question must not invent citations.
        assert negative["citations"] == []
