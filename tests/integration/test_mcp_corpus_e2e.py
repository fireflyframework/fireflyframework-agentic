# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""End-to-end test of the corpus_rag MCP tools against real LLM + embedding APIs.

Drives the FastMCP server in-memory through ``fastmcp.Client`` to verify the
full MCP wire path: ``list_corpora`` (empty) -> ``ingest_corpus_filesystem``
of the synthetic Acme benchmark corpus -> ``list_corpora`` (one entry) ->
``corpus_query`` returning a grounded answer with citations.

A second test exercises mixed-mode ingestion: ``ingest_corpus_filesystem``
for the markdown narrative docs plus ``ingest_corpus_structured`` for the
``acme_corp_billing_ledger.csv`` ledger (schema is inferred via LLM and
the 25k invoice rows land in a normalised SQLite table). The follow-up
``corpus_query`` asks "why is ARR growth decelerating?", which forces
the agent to combine text-to-SQL evidence (aggregated billing rows) with
narrative context (Q4 financials, Q1 all-hands, competitor doc).

Marked ``@pytest.mark.nightly`` because they spend real Anthropic + Azure
OpenAI quota; auto-skip when secrets aren't configured.
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

_REQUIRED_ENV_VARS = ("EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY", "ANTHROPIC_API_KEY")


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
        "ingest_corpus_structured",
        "corpus_retrieve",
        "corpus_query",
    ):
        reg.register(getattr(corpus_rag, name))
    return reg


def _set_e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "corpora"))
    # Match the embedding path nightly CI provides (EMBEDDING_BINDING_HOST/_API_KEY).
    monkeypatch.setenv("EMBEDDING_MODEL", "azure:text-embedding-3-small")
    monkeypatch.setenv("EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANSWER_MODEL", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("RERANK_MODEL", "anthropic:claude-haiku-4-5-20251001")


@pytest.mark.nightly
@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV_VARS),
    reason=f"Requires {', '.join(_REQUIRED_ENV_VARS)}",
)
async def test_mcp_list_ingest_query_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_e2e_env(tmp_path, monkeypatch)

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


@pytest.mark.nightly
@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED_ENV_VARS),
    reason=f"Requires {', '.join(_REQUIRED_ENV_VARS)}",
)
async def test_mcp_structured_plus_unstructured_query_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: ingest .md narrative + structured billing-ledger CSV.

    Verifies that ``corpus_query`` synthesises an answer combining
    text-to-SQL evidence (aggregated billing rows) with retrieved markdown
    context (Q4 financials, Q1 all-hands, competitor doc) when asked a
    question that needs both.

    The CSV billing ledger (single flat table) is preferred over the
    multi-sheet financials spreadsheet for schema-discovery reliability:
    Excel sheets with mixed-type columns and section-header rows can
    exceed the LLM-output validation retry budget, which would make this
    nightly test flaky.
    """
    _set_e2e_env(tmp_path, monkeypatch)

    # Stage a folder with only the markdown narrative docs so the
    # unstructured ingest path doesn't try to chunk the spreadsheets too.
    md_only = tmp_path / "md_only"
    md_only.mkdir()
    md_files = sorted(_BENCH_CORPUS.glob("*.md"))
    for src in md_files:
        (md_only / src.name).write_bytes(src.read_bytes())
    assert len(md_files) == 12, f"expected 12 narrative docs, found {len(md_files)}"

    csv_path = _BENCH_CORPUS / "acme_corp_billing_ledger.csv"
    assert csv_path.is_file(), f"missing synthetic billing ledger at {csv_path}"

    app = create_mcp_app(registry=_build_registry())

    async with Client(app) as client:
        unstructured = (
            await client.call_tool(
                "ingest_corpus_filesystem",
                {"corpus_id": "acme-mixed", "root_path": str(md_only)},
            )
        ).data
        assert unstructured["ingested"] == 12
        assert unstructured["failed"] == 0

        structured = (
            await client.call_tool(
                "ingest_corpus_structured",
                {"corpus_id": "acme-mixed", "path": str(csv_path)},
            )
        ).data
        # The whole CSV must ingest without a hard failure; schema
        # discovery only sees the first few rows so it's reliable on a
        # flat single-table file.
        assert structured["ingested"] == 1, structured
        assert structured["failed"] == 0, structured

        answer = (
            await client.call_tool(
                "corpus_query",
                {
                    "corpus_id": "acme-mixed",
                    "question": (
                        "Why is ARR growth decelerating? Cite specific quarters "
                        "and call out possible drivers from the internal docs."
                    ),
                    "top_k": 6,
                },
            )
        ).data

    text = answer["answer"]
    # The answer must be substantive: narrow factual responses that miss
    # the structured/unstructured fusion would be much shorter.
    assert len(text) > 200, f"answer too thin to be cross-source: {text!r}"
    # Must reference the ARR / growth-rate framing — strong signal that
    # both retrieval branches contributed.
    assert any(token in text for token in ("ARR", "growth", "%")), text
    # Hybrid retrieval over the markdown corpus must contribute at least
    # one citation back to a narrative doc — otherwise the answer is
    # structured-only and fails the cross-source guarantee.
    assert len(answer["citations"]) >= 1, answer
    cited_files = {Path(src["source_path"]).name for src in answer["cited_sources"]}
    assert any(name.endswith(".md") for name in cited_files), f"expected at least one .md citation, got {cited_files}"
