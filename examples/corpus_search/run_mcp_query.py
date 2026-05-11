# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Drive the corpus_rag MCP tools in-process to see real query output.

Usage::

    # First run: ingests the synthetic Acme corpus + billing ledger.
    # Subsequent runs: ledger skips re-ingest, so each invocation just
    # re-queries (~5-10s per question).
    uv run python examples/corpus_search/run_mcp_query.py
    uv run python examples/corpus_search/run_mcp_query.py "Why is ARR growth decelerating?"
    uv run python examples/corpus_search/run_mcp_query.py --reset "What was Q4 2025 revenue?"

Drives a ``fastmcp.Client`` against an in-memory FastMCP server that exposes
the corpus_rag tools — the same code path the e2e nightly test exercises,
but with results printed instead of asserted.

Required env (from .env): ``EMBEDDING_BINDING_HOST``,
``EMBEDDING_BINDING_API_KEY``, ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Client

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.tools.builtins import corpus_rag
from fireflyframework_agentic.tools.registry import ToolRegistry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCH_CORPUS = _REPO_ROOT / "tests" / "examples" / "corpus_search" / "benchmark" / "corpus"
_DEFAULT_CORPUS_ROOT = _REPO_ROOT / "kg" / "mcp-demo"
_DEFAULT_CORPUS_ID = "acme-mixed"
_DEFAULT_QUESTION = (
    "Why is ARR growth decelerating? Cite specific quarters and call out possible drivers from the internal docs."
)


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name in (
        "list_corpora",
        "ingest_corpus_filesystem",
        "ingest_corpus_structured",
        "knowledge_search",
        "corpus_query",
    ):
        reg.register(getattr(corpus_rag, name))
    return reg


def _ensure_env() -> None:
    required = ("EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY", "ANTHROPIC_API_KEY")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.stderr.write(f"missing required env: {', '.join(missing)}\n")
        sys.stderr.write("Set them in .env or export them before running.\n")
        sys.exit(2)
    os.environ.setdefault("EMBEDDING_MODEL", "azure:text-embedding-3-small")
    os.environ.setdefault("EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    os.environ.setdefault("ANSWER_MODEL", "anthropic:claude-sonnet-4-6")
    os.environ.setdefault("RERANK_MODEL", "anthropic:claude-haiku-4-5-20251001")


def _stage_md_only(staging: Path) -> int:
    """Copy only the .md narrative docs into a staging folder.

    The benchmark corpus directory also contains the CSV/XLSX synthetic
    files, which would otherwise be ingested as opaque text by the
    unstructured loader. Mirroring the e2e test, we want clean separation
    between the two ingest modes.
    """
    staging.mkdir(parents=True, exist_ok=True)
    md_files = sorted(_BENCH_CORPUS.glob("*.md"))
    for src in md_files:
        (staging / src.name).write_bytes(src.read_bytes())
    return len(md_files)


async def _run(question: str, corpus_root: Path, reset: bool) -> int:
    if reset and corpus_root.exists():
        shutil.rmtree(corpus_root)
        print(f"[reset] wiped {corpus_root}")

    os.environ["CORPUS_ROOT"] = str(corpus_root)
    md_staging = corpus_root / "_staging" / "md"
    n_md = _stage_md_only(md_staging)
    csv_path = _BENCH_CORPUS / "acme_corp_billing_ledger.csv"

    app = create_mcp_app(registry=_build_registry())
    async with Client(app) as client:
        listed = (await client.call_tool("list_corpora", {})).data
        already = any(c["corpus_id"] == _DEFAULT_CORPUS_ID for c in listed["corpora"])
        if not already:
            print(f"[ingest:unstructured] {n_md} markdown docs ...")
            res = (
                await client.call_tool(
                    "ingest_corpus_filesystem",
                    {"corpus_id": _DEFAULT_CORPUS_ID, "root_path": str(md_staging)},
                )
            ).data
            print(f"  ingested={res['ingested']} skipped={res['skipped']} failed={res['failed']}")

            print(f"[ingest:structured] {csv_path.name} (schema discovery + 25k row insert)...")
            res = (
                await client.call_tool(
                    "ingest_corpus_structured",
                    {"corpus_id": _DEFAULT_CORPUS_ID, "path": str(csv_path)},
                )
            ).data
            print(f"  ingested={res['ingested']} skipped={res['skipped']} failed={res['failed']}")
        else:
            print(f"[ingest] reusing existing corpus at {corpus_root / _DEFAULT_CORPUS_ID}")

        print()
        print(f"[query] {question}")
        print()
        result = (
            await client.call_tool(
                "corpus_query",
                {"corpus_id": _DEFAULT_CORPUS_ID, "question": question, "top_k": 6},
            )
        ).data

    print("=" * 80)
    print("ANSWER")
    print("=" * 80)
    print(result["answer"])
    print()
    if result["cited_sources"]:
        print("Cited sources:")
        for src in result["cited_sources"]:
            print(f"  [{src['chunk_id']}] {Path(src['source_path']).name}")
    elif result["citations"]:
        print(f"Citations (no source path resolved): {result['citations']}")
    else:
        print("(no citations)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("question", nargs="?", default=_DEFAULT_QUESTION, help="Natural-language question.")
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=_DEFAULT_CORPUS_ROOT,
        help=f"Where to keep the ingested corpus. Default: {_DEFAULT_CORPUS_ROOT}",
    )
    parser.add_argument("--reset", action="store_true", help="Wipe corpus-root before ingesting.")
    args = parser.parse_args(argv)

    load_dotenv()
    _ensure_env()
    return asyncio.run(_run(args.question, args.corpus_root, args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
