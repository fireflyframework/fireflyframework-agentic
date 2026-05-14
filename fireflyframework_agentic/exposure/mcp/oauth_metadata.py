# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Public ``/.well-known/*`` endpoints for OAuth 2.0 discovery.

These routes MUST be reachable without authentication — clients fetch
them precisely because they do not yet hold a token. They expose two
documents:

* ``/.well-known/oauth-protected-resource`` (RFC 9728) — tells the
  client *which* authorization server protects this resource and
  *which* scopes apply.
* ``/.well-known/oauth-authorization-server`` (RFC 8414) — minimal
  authorization-server metadata pre-baked from the IdP's values, so
  clients that only consume one well-known URL per resource still
  work without a second hop to the IdP's own well-known document.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from fireflyframework_agentic.exposure.mcp.oauth_jwt import OAuthMetadata


def add_oauth_metadata_routes(app: FastAPI, metadata: OAuthMetadata) -> None:
    """Mount the two well-known metadata endpoints on ``app``."""

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
