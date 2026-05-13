# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""``firefly-mcp-http`` CLI — run the MCP server over Streamable HTTP.

Used by network deployments (e.g. Azure Container Apps). When
``FIREFLY_MCP_CORPUS_AUTH_ENABLED=true`` the process additionally
enforces per-corpus capability tokens fetched from Azure Key Vault —
see ``docs/deploy/mcp-corpus-auth.md``. With the flag off, behaviour is
unchanged: auth is the responsibility of the ingress layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import uvicorn
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.tools.builtins import corpus_rag  # noqa: F401 — registers tools

log = logging.getLogger(__name__)


def build_app() -> FastAPI:
    # Importing corpus_rag above runs the @firefly_tool decorators, which
    # add the tools to the global registry before create_mcp_app() reads it.
    mcp_app = create_mcp_app().http_app(path="/")
    app = FastAPI(title="firefly-mcp", version="0.1.0", lifespan=mcp_app.lifespan)

    if os.environ.get("FIREFLY_MCP_CORPUS_AUTH_ENABLED", "").lower() == "true":
        _install_corpus_auth(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/mcp", mcp_app)
    return app


def _install_corpus_auth(app: FastAPI) -> None:
    """Add CorpusAuthMiddleware. The concrete token store is resolved at
    install time via ``FIREFLY_MCP_TOKEN_STORE_FACTORY``, which points
    at a ``"module.path:callable"`` factory that returns a
    ``CorpusTokenStore``. The default is the Azure Key Vault factory
    that ships with the corpus-search example, so existing deployments
    keep working out of the box; operators on a non-Azure back-end set
    the env var to their own factory and the framework needs no Azure
    deps to run.
    """
    vault_url = os.environ.get("FIREFLY_MCP_KEYVAULT_URL")
    if not vault_url:
        raise RuntimeError("FIREFLY_MCP_CORPUS_AUTH_ENABLED=true but FIREFLY_MCP_KEYVAULT_URL is unset")

    factory_spec = os.environ.get(
        "FIREFLY_MCP_TOKEN_STORE_FACTORY",
        "examples.corpus_search.azure_security:build_default_store",
    )

    from fireflyframework_agentic.exposure.mcp.auth import CorpusAuthMiddleware
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    ttl = float(os.environ.get("FIREFLY_MCP_TOKEN_CACHE_TTL_SECONDS", "300"))
    prefix = os.environ.get("FIREFLY_MCP_TOKEN_SECRET_PREFIX", "firefly-mcp-corpus-token-")

    factory = _resolve_factory(factory_spec)
    store = factory(vault_url=vault_url, prefix=prefix)
    cache = CorpusTokenCache(ttl_seconds=ttl)
    app.add_middleware(CorpusAuthMiddleware, store=store, cache=cache, mount_path="/mcp")


def _resolve_factory(spec: str):
    """Resolve ``"module.path:callable"`` to the callable itself.

    Raises ``RuntimeError`` with a clear message if the module or
    attribute cannot be imported / found — the alternative (a confusing
    ImportError at first request) makes ops debugging much harder.
    """
    import importlib

    module_path, _, attr = spec.partition(":")
    if not module_path or not attr:
        raise RuntimeError(f"FIREFLY_MCP_TOKEN_STORE_FACTORY must look like 'pkg.mod:callable', got {spec!r}")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot import token-store factory module {module_path!r}: {exc}. "
            "If you are using the default Azure-Key-Vault factory, install the "
            "corpus_search example deps or point "
            "FIREFLY_MCP_TOKEN_STORE_FACTORY at your own factory."
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise RuntimeError(f"Factory {spec!r} resolved to a module without attribute {attr!r}") from exc


def _log_unhandled_loop_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """asyncio loop exception handler that logs full tracebacks to stderr.

    Without this, a task that fails after the HTTP response is sent (the
    request's response writer raising on cleanup; a background coroutine
    scheduled by a tool; a stream handler exception triggered by an SSE
    long-poll teardown) is silently dropped: asyncio logs it at ``ERROR``
    on the ``asyncio`` logger and uvicorn doesn't surface those by
    default. Operators see the symptom (connections terminate, bridge
    reconnects, server "looks down") with no explanation.

    Routing through our own logger gives us:
      * The exception traceback (``loop.default_exception_handler`` writes
        it via ``logger.error`` but it's swallowed by uvicorn's default
        log config).
      * Any context keys asyncio attached (handle, source_traceback, …).

    Does NOT change loop behaviour or swallow exceptions — it just
    ensures they're visible. The loop continues running; the server
    stays up. Only the originating task dies.
    """
    message = context.get("message", "<no message>")
    exc = context.get("exception")
    handle = context.get("handle")
    future = context.get("future")
    task = context.get("task")
    src = task or future or handle
    if exc is not None:
        log.error(
            "asyncio: unhandled exception in %s: %s",
            src,
            message,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
        log.error("asyncio: %s (source=%s)", message, src)


def main() -> None:
    """Entry point registered as ``firefly-mcp-http`` in ``[project.scripts]``.

    Loads ``.env`` from the current working directory (or any ancestor) so
    a developer running the server from a project directory gets its
    variables (``EMBEDDING_MODEL``, ``FIREFLY_MCP_KEYVAULT_URL``, …)
    without an explicit shell ``source``. ``usecwd=True`` anchors the
    search on cwd (the default would walk up from this module's
    install location, which is wrong for a CLI). Real environment
    variables always win — ``load_dotenv`` defaults to ``override=False``
    — so Azure / Container Apps deploys, which inject env from the
    manifest before the process starts, see no behavioural change.
    """
    load_dotenv(find_dotenv(usecwd=True))

    # Force-attach our handler before uvicorn boots its loop. uvicorn picks
    # up loop="auto" → uvloop on Unix; both honour ``set_exception_handler``.
    # We can't set it on uvicorn's not-yet-created loop, so we do it via a
    # ``run_in_executor``-free hook: register on the current loop if any,
    # and also set the default factory so the loop uvicorn creates inherits
    # it. The "set on current loop" path covers ``uvicorn.run`` invocations
    # where uvicorn reuses the calling loop.
    try:
        current = asyncio.get_event_loop()
    except RuntimeError:
        current = None
    if current is not None:
        current.set_exception_handler(_log_unhandled_loop_exception)
    # Ensure stderr-level logging is wired so the handler's records reach
    # the operator. uvicorn configures its own loggers; touching the root
    # logger with a minimal config is safe and idempotent.
    logging.basicConfig(level=os.environ.get("FIREFLY_MCP_LOG_LEVEL", "INFO"))

    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(build_app(), host="0.0.0.0", port=port)
    server = uvicorn.Server(config)

    # Re-attach the handler after uvicorn creates / acquires its loop.
    # ``Server.run`` calls ``asyncio.run`` which spins up a fresh loop;
    # we hook the loop-startup via a one-shot task scheduled by the
    # lifespan, but the simplest reliable path is to wrap ``run`` and
    # set the handler from inside the new loop.
    async def _serve() -> None:
        asyncio.get_running_loop().set_exception_handler(_log_unhandled_loop_exception)
        await server.serve()

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
