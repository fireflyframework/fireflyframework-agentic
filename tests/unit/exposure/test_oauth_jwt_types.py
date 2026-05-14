# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for OAuth metadata + TokenVerifier protocol."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from fireflyframework_agentic.exposure.mcp.oauth_jwt import (
    OAuthMetadata,
    TokenVerifier,
)


def _metadata() -> OAuthMetadata:
    return OAuthMetadata(
        issuer="https://login.example.com/v2.0",
        authorization_endpoint="https://login.example.com/authorize",
        token_endpoint="https://login.example.com/token",
        jwks_uri="https://login.example.com/keys",
        resource="https://mcp.example.com/mcp/",
        scopes_supported=("user_impersonation",),
    )


def test_metadata_holds_values() -> None:
    md = _metadata()
    assert md.issuer == "https://login.example.com/v2.0"
    assert md.scopes_supported == ("user_impersonation",)


def test_metadata_is_frozen() -> None:
    md = _metadata()
    with pytest.raises(dataclasses.FrozenInstanceError):
        md.issuer = "tampered"  # type: ignore[misc]


def test_token_verifier_protocol_runtime_checkable() -> None:
    class Stub:
        def validate_token(self, token: str) -> dict[str, Any]:
            return {"sub": token}

    assert isinstance(Stub(), TokenVerifier)


def test_non_verifier_fails_protocol_check() -> None:
    class NotAVerifier:
        pass

    assert not isinstance(NotAVerifier(), TokenVerifier)
