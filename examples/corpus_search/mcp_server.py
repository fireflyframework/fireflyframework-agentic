# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Stdio MCP server exposing the corpus_rag tools (incl. structured ingest).

Run as a subprocess of any MCP client (Claude Desktop, Claude Code,
mcp-cli, etc.). The client speaks JSON-RPC over the server's stdin/
stdout; everything else (logs, errors, status) goes to stderr.

Usage::

    # Smoke test in a terminal — sends "initialize" + waits.
    # Press Ctrl-D to close stdin and exit.
    uv run python examples/corpus_search/mcp_server.py

    # Wire to Claude Code (per-user, persistent across sessions):
    claude mcp add firefly-corpus -- \\
        uv --directory /Users/javi/work/fireflyframework-agentic run python \\
        examples/corpus_search/mcp_server.py

    # Or per-project, by adding to .claude/settings.json under "mcpServers".

Required env (read from .env at startup): ``EMBEDDING_BINDING_HOST``,
``EMBEDDING_BINDING_API_KEY``, ``ANTHROPIC_API_KEY``. Optional:
``CORPUS_ROOT`` (default ``/tmp/firefly/corpora``).

CRITICAL: this script never writes to stdout itself. The MCP wire
protocol owns stdout; any stray ``print()`` would corrupt frames.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.tools.builtins import corpus_rag
from fireflyframework_agentic.tools.builtins.corpus_rag import _shutdown_agents
from fireflyframework_agentic.tools.registry import ToolRegistry

_REQUIRED_ENV_VARS = ("EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY", "ANTHROPIC_API_KEY")


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name in (
        "list_corpora",
        "ingest_corpus_filesystem",
        "discover_corpus_schema",
        "ingest_corpus_structured",
        "knowledge_search",
        "corpus_query",
        "list_corpus_schemas",
        "corpus_sql",
    ):
        reg.register(getattr(corpus_rag, name))
    return reg


@contextlib.asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[None]:
    log = logging.getLogger("firefly.mcp_server")
    try:
        yield
    finally:
        log.info("shutting down — closing cached corpus agents")
        await _shutdown_agents()


def _ensure_env() -> None:
    missing = [k for k in _REQUIRED_ENV_VARS if not os.environ.get(k)]
    if missing:
        sys.stderr.write(f"[mcp_server] missing required env: {', '.join(missing)}\n")
        sys.stderr.write("[mcp_server] set them in .env or pass via the MCP client config\n")
        sys.exit(2)
    os.environ.setdefault("EMBEDDING_MODEL", "azure:text-embedding-3-small")
    os.environ.setdefault("EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    os.environ.setdefault("ANSWER_MODEL", "anthropic:claude-sonnet-4-6")
    os.environ.setdefault("RERANK_MODEL", "anthropic:claude-haiku-4-5-20251001")


def main() -> int:
    # Load .env from the repo root so `claude mcp add` configurations that
    # set --directory pick up the operator's secrets without needing to
    # duplicate them in the MCP client config.
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")

    # All logs to stderr — stdout is reserved for the MCP wire protocol.
    logging.basicConfig(
        stream=sys.stderr,
        level=os.environ.get("FIREFLY_AGENTIC_LOG_LEVEL", "INFO"),
        format="[mcp_server] %(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # PDF / HTTP libraries are noisy; keep them quiet unless explicitly opted in.
    for noisy in ("pdfminer", "pdfplumber", "azure", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _ensure_env()

    log = logging.getLogger("firefly.mcp_server")
    corpus_root = os.environ.get("CORPUS_ROOT", "/tmp/firefly/corpora")
    log.info("starting firefly corpus_rag MCP server (CORPUS_ROOT=%s)", corpus_root)

    app = create_mcp_app(
        name="firefly-corpus",
        registry=_build_registry(),
        lifespan=_lifespan,
    )
    # FastMCP.run() defaults to stdio transport — exactly what local MCP
    # clients (Claude Desktop / Code, mcp-cli) expect when invoked as a
    # subprocess.
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
