# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for the static API-key verifier and CompositeVerifier."""

from __future__ import annotations

import pytest

pytest.importorskip("jwt", reason="composite factory builds an Entra verifier under the hood")
pytest.importorskip("azure.identity", reason="azure_security imports azure.identity transitively")

from examples.corpus_search.azure_security import (
    CompositeVerifier,
    StaticApiKeyVerifier,
    build_composite_verifier,
)


def test_static_key_match_returns_synth_claims() -> None:
    v = StaticApiKeyVerifier("s3cret", ("alpha", "beta"))
    claims = v.validate_token("s3cret")
    assert claims["sub"] == "static-api-key"
    assert set(claims["roles"]) == {"Corpus.alpha.Write", "Corpus.beta.Write"}


def test_static_key_mismatch_raises() -> None:
    v = StaticApiKeyVerifier("s3cret", ("alpha",))
    with pytest.raises(ValueError, match="Static key mismatch"):
        v.validate_token("wrong")


def test_static_key_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        StaticApiKeyVerifier("", ("alpha",))


def test_composite_returns_first_accepting_verifier() -> None:
    class _Accept:
        def validate_token(self, token: str) -> dict[str, object]:
            return {"sub": "ok"}

    class _Reject:
        def validate_token(self, token: str) -> dict[str, object]:
            raise ValueError("nope")

    c = CompositeVerifier(_Reject(), _Accept())
    assert c.validate_token("x") == {"sub": "ok"}


def test_composite_reraises_last_when_all_reject() -> None:
    class _Reject:
        def __init__(self, msg: str) -> None:
            self._msg = msg

        def validate_token(self, token: str) -> dict[str, object]:
            raise ValueError(self._msg)

    c = CompositeVerifier(_Reject("first"), _Reject("second"))
    with pytest.raises(ValueError, match="second"):
        c.validate_token("x")


def test_composite_requires_one_verifier() -> None:
    with pytest.raises(ValueError, match="at least one"):
        CompositeVerifier()


def test_build_composite_with_static_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.setenv("FIREFLY_MCP_STATIC_API_KEY", "shared-secret")
    monkeypatch.setenv("FIREFLY_MCP_STATIC_API_KEY_CORPORA", "alpha, beta ,gamma")
    c = build_composite_verifier()
    claims = c.validate_token("shared-secret")
    assert set(claims["roles"]) == {
        "Corpus.alpha.Write",
        "Corpus.beta.Write",
        "Corpus.gamma.Write",
    }


def test_build_composite_without_static_key_falls_back_to_entra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.delenv("FIREFLY_MCP_STATIC_API_KEY", raising=False)
    monkeypatch.delenv("FIREFLY_MCP_STATIC_API_KEY_CORPORA", raising=False)
    c = build_composite_verifier()
    with pytest.raises(ValueError):
        c.validate_token("anything")
