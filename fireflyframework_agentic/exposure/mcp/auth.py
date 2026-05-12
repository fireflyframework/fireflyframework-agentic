# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Starlette middleware that authorises MCP tool calls against per-corpus
capability tokens stored in Azure Key Vault.

Scope: this middleware validates that the bearer the client sent equals
the current value of ``firefly-mcp-corpus-token-<corpus_id>`` for the
corpus the tool call targets. It does not mint, rotate, or revoke
tokens; those operations are performed out-of-band via the Azure CLI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fireflyframework_agentic.security.keyvault import (
    CorpusTokenCache,
    KeyVaultTokenStore,
    corpus_token_digest,
)

logger = logging.getLogger(__name__)

_EXCLUDED_PATHS: frozenset[str] = frozenset({"/healthz"})
_JSONRPC_ERR_AUTH = -32001

# Required on every gated request. The bearer is per-corpus and the value
# of this header binds it to a specific corpus_id so the middleware can
# validate against KV at handshake time — without it, lifecycle methods
# (initialize, tools/list, …) and cross-corpus tools (list_corpora) would
# go through on bearer-presence alone, letting an outsider enumerate the
# tool schemas or, worse, the list of corpora that exist.
CORPUS_ID_HEADER = "X-Firefly-Corpus-Id"

# MCP lifecycle methods that do not operate on a single corpus's data.
# They still require a valid bearer/corpus-id pair (checked from the
# header), but they don't need a body-side ``corpus_id`` argument.
_LIFECYCLE_METHODS: frozenset[str] = frozenset(
    {"initialize", "initialized", "ping", "tools/list", "resources/list", "prompts/list"}
)

# Tools that intentionally do not take a ``corpus_id`` argument because they
# operate above the corpus boundary (discovery / metadata). They still
# require a valid header-bound bearer; the tool's output is scoped by
# ``authorised_corpora_var`` to the caller's authorised corpus.
_NO_CORPUS_TOOLS: frozenset[str] = frozenset({"list_corpora"})


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": _JSONRPC_ERR_AUTH, "message": detail}},
        status_code=status,
    )


def _token_fingerprint(token: str) -> str:
    """Stable, non-reversible 8-char prefix for log lines."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


class CorpusAuthMiddleware(BaseHTTPMiddleware):
    """Authorise MCP tool calls against a per-corpus capability token.

    The middleware is mount-aware: only requests whose path is exactly
    ``mount_path`` or under ``mount_path/`` are gated. Everything else
    (notably ``/healthz``) is passed through.

    Failure modes:
        - ``401`` — missing / malformed ``Authorization`` header.
        - ``400`` — body has no ``corpus_id`` argument.
        - ``403`` — bearer does not match the current Key Vault secret for
          this corpus (also returned for unknown corpora to prevent
          enumeration).
        - ``503`` — Key Vault unreachable for an un-cached corpus.
    """

    def __init__(
        self,
        app: Any,
        *,
        store: KeyVaultTokenStore,
        cache: CorpusTokenCache,
        mount_path: str = "/mcp",
    ) -> None:
        super().__init__(app)
        self._store = store
        self._cache = cache
        self._mount = mount_path.rstrip("/") or "/"

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path in _EXCLUDED_PATHS:
            return await call_next(request)
        if not (path == self._mount or path.startswith(self._mount + "/")):
            return await call_next(request)

        # Authn pre-flight: every gated request must carry BOTH a bearer
        # and X-Firefly-Corpus-Id, and the bearer must match the KV secret
        # for that corpus. This runs BEFORE we look at the body, so it
        # closes the previous gap where lifecycle methods (initialize,
        # tools/list) and no-corpus tools (list_corpora) only checked
        # bearer presence — letting any attacker enumerate the universe
        # of tools or corpus_ids on the server.
        bearer = self._read_bearer(request)
        if bearer is None:
            return _err(401, "Missing or malformed Authorization header")
        header_corpus_id = request.headers.get(CORPUS_ID_HEADER, "").strip()
        if not header_corpus_id:
            return _err(401, f"Missing {CORPUS_ID_HEADER} header")

        digest = corpus_token_digest(bearer, header_corpus_id)
        outcome = await self._authorise(header_corpus_id, bearer, digest)
        if outcome == "outage":
            return _err(503, "Key Vault unavailable")
        if outcome == "deny":
            return _err(403, "Forbidden for this corpus")

        _set_authorised_corpora((header_corpus_id,))

        # Non-POST (SSE GET) and lifecycle / no-corpus paths: header-bound
        # auth is sufficient; no body-side corpus_id is expected.
        if request.method != "POST":
            return await call_next(request)
        body = await request.body()
        request._body = body  # type: ignore[attr-defined]
        method = self._extract_method(body)
        if method is not None and (method in _LIFECYCLE_METHODS or method.startswith("notifications/")):
            return await call_next(request)
        tool_name = self._extract_tool_name(body)
        if tool_name in _NO_CORPUS_TOOLS:
            return await call_next(request)

        # tools/call against a corpus-scoped tool: body MUST carry corpus_id
        # and it MUST match the header. Mismatch is a hard 403 so a token
        # for corpus A can never be used to call a tool against corpus B
        # by smuggling a different ID into the body.
        body_corpus_id = self._extract_corpus_id(body)
        if body_corpus_id is None:
            return _err(400, "Missing corpus_id in tool arguments")
        if body_corpus_id != header_corpus_id:
            logger.info(
                "corpus_auth: deny (header/body mismatch) header=%s body=%s token=%s",
                header_corpus_id,
                body_corpus_id,
                _token_fingerprint(bearer),
            )
            return _err(403, "corpus_id in arguments does not match header")
        return await call_next(request)

    @staticmethod
    def _read_bearer(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        return token or None

    @staticmethod
    def _extract_tool_name(body: bytes) -> str | None:
        if not body:
            return None
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return None
        first = doc[0] if isinstance(doc, list) else doc
        params = first.get("params") if isinstance(first, dict) else None
        if isinstance(params, dict):
            name = params.get("name")
            if isinstance(name, str):
                return name
        return None

    @staticmethod
    def _extract_method(body: bytes) -> str | None:
        if not body:
            return None
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return None
        first = doc[0] if isinstance(doc, list) else doc
        if isinstance(first, dict):
            value = first.get("method")
            if isinstance(value, str):
                return value
        return None

    @staticmethod
    def _extract_corpus_id(body: bytes) -> str | None:
        if not body:
            return None
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return None
        first = doc[0] if isinstance(doc, list) else doc
        params = first.get("params") if isinstance(first, dict) else None
        args = params.get("arguments") if isinstance(params, dict) else None
        if isinstance(args, dict):
            value = args.get("corpus_id")
            if isinstance(value, str) and value:
                return value
        return None

    async def _authorise(self, corpus_id: str, token: str, digest: str) -> str:
        """Return ``"allow"``, ``"deny"``, or ``"outage"``."""
        if self._cache.is_trusted(corpus_id, digest):
            logger.debug(
                "corpus_auth: cache hit corpus_id=%s token=%s",
                corpus_id,
                _token_fingerprint(token),
            )
            return "allow"
        try:
            secret = await self._store.get_corpus_token(corpus_id)
        except Exception:  # noqa: BLE001 — fail-closed; alternative is opening auth.
            logger.exception("corpus_auth: Key Vault lookup failed corpus_id=%s", corpus_id)
            return "outage"
        if secret is None:
            logger.info(
                "corpus_auth: deny (no secret) corpus_id=%s token=%s",
                corpus_id,
                _token_fingerprint(token),
            )
            return "deny"
        if not hmac.compare_digest(secret, token):
            logger.info(
                "corpus_auth: deny (mismatch) corpus_id=%s token=%s",
                corpus_id,
                _token_fingerprint(token),
            )
            return "deny"
        self._cache.remember(corpus_id, digest)
        return "allow"


def _set_authorised_corpora(corpora: tuple[str, ...]) -> None:
    """Publish authorised corpora to the corpus_rag contextvar.

    Imported lazily to avoid an import cycle: the tools module imports
    framework primitives, which would otherwise pull this middleware in
    when only the stdio transport is used.
    """
    from fireflyframework_agentic.tools.builtins.corpus_rag import (
        authorised_corpora_var,
    )

    authorised_corpora_var.set(corpora)
