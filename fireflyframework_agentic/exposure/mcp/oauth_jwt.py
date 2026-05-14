# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Provider-agnostic OAuth 2.0 / OIDC primitives for the MCP HTTP exposure.

Holds only generic OAuth concepts (issuer, JWKS URI, audience, scopes,
roles claim). Provider-specific factories (Entra, Okta, Auth0, …) live
in ``examples/`` and inject these types via the factory env vars
resolved in :mod:`fireflyframework_agentic.exposure.mcp.http_cli`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


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
