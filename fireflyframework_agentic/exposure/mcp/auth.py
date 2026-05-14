# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""OAuth 2.0 / OIDC auth for the MCP HTTP exposure.

Three responsibilities, all provider-agnostic:

* ``OAuthMetadata`` / ``TokenVerifier`` / ``RequiredRoleFn`` — the types
  the middleware depends on. Concrete providers (Entra, Okta, …) live in
  ``examples/`` and are injected by
  :mod:`fireflyframework_agentic.exposure.mcp.http_cli` at startup.
* :func:`add_oauth_metadata_routes` — mounts the two public
  ``/.well-known/`` documents (RFC 9728 + RFC 8414) so MCP clients can
  bootstrap OAuth login automatically.
* :class:`OAuthJWTMiddleware` — Starlette middleware that validates
  bearer tokens via the supplied ``TokenVerifier`` and enforces
  App-Roles RBAC.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider-agnostic types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthMetadata:
    """Static OAuth 2.0 / OIDC metadata advertised by the server.

    Populated by an operator-supplied factory at startup and rendered at
    ``/.well-known/oauth-protected-resource`` and
    ``/.well-known/oauth-authorization-server``.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    resource: str
    scopes_supported: tuple[str, ...]


@runtime_checkable
class TokenVerifier(Protocol):
    """Verifies a bearer token and returns its claims dict.

    Implementations: ``EntraTokenVerifier`` (examples/corpus_search) or any
    other provider-specific RBACManager subclass. Must raise ``ValueError``
    on any validation failure — the middleware maps that to ``401``.
    """

    def validate_token(self, token: str) -> dict[str, Any]: ...


RequiredRoleFn = Callable[[str, str], str | None]
"""``(tool_name, corpus_id) -> role_value`` mapping for App-Roles RBAC.

Returning ``None`` means the call requires no per-corpus role (lifecycle /
no-corpus tools). Mapping is injected so deployments can adopt different
naming conventions without forking the middleware."""


# ---------------------------------------------------------------------------
# Public /.well-known/ discovery routes (RFC 9728 + RFC 8414)
# ---------------------------------------------------------------------------


def add_oauth_metadata_routes(app: FastAPI, metadata: OAuthMetadata) -> None:
    """Mount the two well-known metadata endpoints on ``app``.

    These routes MUST be reachable without authentication — clients
    fetch them precisely because they do not yet hold a token.
    """

    @app.get("/.well-known/oauth-protected-resource")
    def protected_resource() -> dict[str, Any]:
        return {
            "resource": metadata.resource,
            "authorization_servers": [metadata.issuer],
            "scopes_supported": list(metadata.scopes_supported),
            "bearer_methods_supported": ["header"],
        }

    @app.get("/.well-known/oauth-authorization-server")
    def authorization_server() -> dict[str, Any]:
        return {
            "issuer": metadata.issuer,
            "authorization_endpoint": metadata.authorization_endpoint,
            "token_endpoint": metadata.token_endpoint,
            "jwks_uri": metadata.jwks_uri,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
        }


# ---------------------------------------------------------------------------
# OAuth JWT middleware
# ---------------------------------------------------------------------------

_EXCLUDED_PATHS: frozenset[str] = frozenset({"/healthz"})
_JSONRPC_ERR_AUTH = -32001

# MCP lifecycle methods that do not target a specific corpus. They still
# require a valid token but skip the per-corpus role check.
_LIFECYCLE_METHODS: frozenset[str] = frozenset(
    {"initialize", "initialized", "ping", "tools/list", "resources/list", "prompts/list"}
)

# Tools that intentionally take no ``corpus_id`` argument because they
# operate above the corpus boundary. They still require a valid token;
# their output is scoped to the caller's authorised corpora via the
# ``authorised_corpora_var`` contextvar.
_NO_CORPUS_TOOLS: frozenset[str] = frozenset({"list_corpora"})


def _err(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": _JSONRPC_ERR_AUTH, "message": detail}},
        status_code=status,
        headers=headers,
    )


def _token_fingerprint(token: str) -> str:
    """Stable, non-reversible 8-char prefix for log lines."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


def _corpus_id_fingerprint(corpus_id: str) -> str:
    """Stable, non-reversible 8-char prefix for log lines.

    ``corpus_id`` often encodes customer-identifying information, so the
    raw value is never logged — only this prefix — to keep downstream log
    aggregation safe.
    """
    return hashlib.sha256(corpus_id.encode()).hexdigest()[:8]


class OAuthJWTMiddleware(BaseHTTPMiddleware):
    """Validate OAuth 2.0 bearer tokens and enforce App-Roles RBAC.

    Failure modes:
        - ``401`` — missing/malformed bearer or token validation failed.
          Response includes ``WWW-Authenticate`` pointing at the
          ``/.well-known/oauth-protected-resource`` document, per RFC 9728.
        - ``400`` — body is missing ``corpus_id`` for a corpus-scoped tool.
        - ``403`` — caller lacks the App Role required for this
          ``(tool, corpus_id)`` pair.
    """

    def __init__(
        self,
        app: Any,
        *,
        verifier: TokenVerifier,
        required_role_fn: RequiredRoleFn,
        roles_claim: str = "roles",
        mount_path: str = "/mcp",
        metadata_url: str,
    ) -> None:
        super().__init__(app)
        self._verifier = verifier
        self._required_role_fn = required_role_fn
        self._roles_claim = roles_claim
        self._mount = mount_path.rstrip("/") or "/"
        self._metadata_url = metadata_url

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path in _EXCLUDED_PATHS:
            return await call_next(request)
        if not (path == self._mount or path.startswith(self._mount + "/")):
            return await call_next(request)

        bearer = self._read_bearer(request)
        if bearer is None:
            return self._unauthorized("Missing or malformed Authorization header")

        try:
            claims = self._verifier.validate_token(bearer)
        except ValueError:
            return self._unauthorized("Invalid or expired token")

        roles = self._extract_roles(claims)

        if request.method != "POST":
            self._publish_authorised_corpora(roles)
            return await call_next(request)

        body = await request.body()
        request._body = body  # type: ignore[attr-defined]
        method = self._extract_method(body)

        if method is not None and (method in _LIFECYCLE_METHODS or method.startswith("notifications/")):
            self._publish_authorised_corpora(roles)
            return await call_next(request)

        tool_name = self._extract_tool_name(body)
        if tool_name in _NO_CORPUS_TOOLS:
            self._publish_authorised_corpora(roles)
            return await call_next(request)

        body_corpus_id = self._extract_corpus_id(body)
        if body_corpus_id is None:
            return _err(400, "Missing corpus_id in tool arguments")

        if tool_name is None:
            return _err(400, "Missing tool name in tool call")

        required = self._required_role_fn(tool_name, body_corpus_id)
        if required is not None and not self._has_role(roles, required):
            logger.info(
                "oauth_auth: deny corpus=%s tool=%s token=%s required=%s",
                _corpus_id_fingerprint(body_corpus_id),
                tool_name,
                _token_fingerprint(bearer),
                required,
            )
            return _err(403, "Forbidden for this corpus")

        self._publish_authorised_corpora(roles)
        return await call_next(request)

    def _unauthorized(self, detail: str) -> JSONResponse:
        """Build a RFC 6750-shaped 401.

        The ``WWW-Authenticate`` header carries the OAuth 2.0 challenge
        (``realm``, ``error``, ``error_description``) plus the RFC 9728
        ``resource_metadata`` parameter that tells the client where to
        discover the authorization server. The body uses the OAuth error
        format (``error`` / ``error_description``) rather than JSON-RPC
        — clients implementing the MCP Authorization spec look for that
        shape to recognise an OAuth-protected resource.
        """
        challenge = (
            f'Bearer realm="OAuth", '
            f'resource_metadata="{self._metadata_url}", '
            f'error="invalid_token", '
            f'error_description="{detail}"'
        )
        return JSONResponse(
            {"error": "invalid_token", "error_description": detail},
            status_code=401,
            headers={"WWW-Authenticate": challenge},
        )

    def _extract_roles(self, claims: dict[str, Any]) -> tuple[str, ...]:
        raw = claims.get(self._roles_claim, [])
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, list):
            return tuple(r for r in raw if isinstance(r, str))
        return ()

    @staticmethod
    def _has_role(roles: tuple[str, ...], required: str) -> bool:
        """Return ``True`` if ``required`` is granted by ``roles``.

        ``Corpus.<id>.Write`` implies ``Corpus.<id>.Read`` — the implication
        is enforced here rather than in the IdP so operators only assign
        the higher-privilege role.
        """
        if required in roles:
            return True
        if required.endswith(".Read"):
            implied_write = required[: -len(".Read")] + ".Write"
            if implied_write in roles:
                return True
        return False

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

    @staticmethod
    def _publish_authorised_corpora(roles: tuple[str, ...]) -> None:
        """Publish authorised corpora to the corpus_rag contextvar.

        Imported lazily to avoid an import cycle: the tools module imports
        framework primitives, which would otherwise pull this middleware
        in when only the stdio transport is used.
        """
        from fireflyframework_agentic.tools.builtins.corpus_rag import (
            authorised_corpora_var,
        )

        authorised: set[str] = set()
        for role in roles:
            if not role.startswith("Corpus."):
                continue
            rest = role[len("Corpus.") :]
            if rest.endswith(".Read"):
                authorised.add(rest[: -len(".Read")])
            elif rest.endswith(".Write"):
                authorised.add(rest[: -len(".Write")])
        authorised_corpora_var.set(tuple(sorted(authorised)))
