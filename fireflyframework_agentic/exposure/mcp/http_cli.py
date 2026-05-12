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

import os

import uvicorn
from fastapi import FastAPI

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app
from fireflyframework_agentic.tools.builtins import corpus_rag  # noqa: F401 — registers tools


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


def main() -> None:
    """Entry point registered as ``firefly-mcp-http`` in ``[project.scripts]``."""
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
