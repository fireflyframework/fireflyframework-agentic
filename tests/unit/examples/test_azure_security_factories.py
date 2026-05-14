# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for ``build_entra_verifier`` / ``build_entra_metadata`` factories."""

from __future__ import annotations

import pytest

pytest.importorskip("jwt", reason="factories use pyjwt")
pytest.importorskip("azure.identity", reason="factories import azure.identity transitively")

from examples.corpus_search.azure_security import (
    EntraTokenVerifier,
    build_entra_metadata,
    build_entra_verifier,
)
from fireflyframework_agentic.exposure.mcp.auth import OAuthMetadata


def test_verifier_factory_returns_entra_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    v = build_entra_verifier()
    assert isinstance(v, EntraTokenVerifier)


def test_verifier_factory_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="AZURE_TENANT_ID"):
        build_entra_verifier()


def test_metadata_factory_returns_populated_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.setenv("FIREFLY_MCP_PUBLIC_URL", "https://mcp.example.com")
    md = build_entra_metadata()
    assert isinstance(md, OAuthMetadata)
    assert md.issuer == "https://login.microsoftonline.com/tenant-guid/v2.0"
    assert md.jwks_uri.endswith("/discovery/v2.0/keys")
    assert md.resource == "https://mcp.example.com/mcp/"
    assert md.scopes_supported == ("api://client-guid/user_impersonation",)


def test_metadata_factory_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "t")
    monkeypatch.setenv("AZURE_CLIENT_ID", "c")
    monkeypatch.setenv("FIREFLY_MCP_PUBLIC_URL", "https://mcp.example.com/")
    md = build_entra_metadata()
    assert md.resource == "https://mcp.example.com/mcp/"


def test_metadata_factory_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("FIREFLY_MCP_PUBLIC_URL", raising=False)
    with pytest.raises(RuntimeError, match="AZURE_TENANT_ID"):
        build_entra_metadata()
