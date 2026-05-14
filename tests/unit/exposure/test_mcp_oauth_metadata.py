# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for OAuth /.well-known/ metadata endpoints."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fireflyframework_agentic.exposure.mcp.oauth_jwt import OAuthMetadata
from fireflyframework_agentic.exposure.mcp.oauth_metadata import (
    add_oauth_metadata_routes,
)


def _md() -> OAuthMetadata:
    return OAuthMetadata(
        issuer="https://login.example.com/v2.0",
        authorization_endpoint="https://login.example.com/authorize",
        token_endpoint="https://login.example.com/token",
        jwks_uri="https://login.example.com/keys",
        resource="https://mcp.example.com/mcp/",
        scopes_supported=("user_impersonation",),
    )


def _client() -> TestClient:
    app = FastAPI()
    add_oauth_metadata_routes(app, _md())
    return TestClient(app)


def test_protected_resource_endpoint_shape() -> None:
    body = _client().get("/.well-known/oauth-protected-resource").json()
    assert body["resource"] == "https://mcp.example.com/mcp/"
    assert body["authorization_servers"] == ["https://login.example.com/v2.0"]
    assert body["scopes_supported"] == ["user_impersonation"]
    assert body["bearer_methods_supported"] == ["header"]


def test_authorization_server_endpoint_shape() -> None:
    body = _client().get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == "https://login.example.com/v2.0"
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["jwks_uri"].endswith("/keys")
    assert "code" in body["response_types_supported"]
    assert "S256" in body["code_challenge_methods_supported"]


def test_metadata_routes_are_public() -> None:
    """Metadata MUST be reachable without auth — clients fetch it before login."""
    client = _client()
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200
