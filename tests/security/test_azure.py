# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for Entra ID token verification and OBO exchange."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fireflyframework_agentic.config import FireflyAgenticConfig
from fireflyframework_agentic.security.azure import EntraOBOClient, EntraTokenVerifier
from fireflyframework_agentic.security.rbac import RBACManager


@pytest.fixture
def rsa_keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def fake_jwk_client(rsa_keypair: rsa.RSAPrivateKey) -> Any:
    public_key = rsa_keypair.public_key()

    class _FakeSigningKey:
        def __init__(self, key: Any) -> None:
            self.key = key

    class _FakeJWKClient:
        def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
            return _FakeSigningKey(public_key)

    return _FakeJWKClient()


def _sign(private_key: rsa.RSAPrivateKey, claims: dict[str, Any]) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256")


def _entra_v2_iss(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/v2.0"


def test_verifier_rejects_garbage_token(fake_jwk_client: Any) -> None:
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    with pytest.raises(ValueError):
        verifier.verify("not-a-real-token")


def test_verifier_accepts_valid_rs256_token(rsa_keypair: rsa.RSAPrivateKey, fake_jwk_client: Any) -> None:
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    now = int(time.time())
    token = _sign(
        rsa_keypair,
        {
            "iss": _entra_v2_iss("t"),
            "aud": "api://app",
            "sub": "user-1",
            "exp": now + 60,
            "iat": now,
        },
    )
    claims = verifier.verify(token)
    assert claims["sub"] == "user-1"
    assert claims["aud"] == "api://app"


def test_verifier_rejects_expired_token(rsa_keypair: rsa.RSAPrivateKey, fake_jwk_client: Any) -> None:
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    now = int(time.time())
    token = _sign(
        rsa_keypair,
        {
            "iss": _entra_v2_iss("t"),
            "aud": "api://app",
            "sub": "user-1",
            "exp": now - 60,
            "iat": now - 120,
        },
    )
    with pytest.raises(ValueError, match="expired"):
        verifier.verify(token)


def test_verifier_rejects_wrong_audience(rsa_keypair: rsa.RSAPrivateKey, fake_jwk_client: Any) -> None:
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    now = int(time.time())
    token = _sign(
        rsa_keypair,
        {
            "iss": _entra_v2_iss("t"),
            "aud": "api://other-app",
            "sub": "user-1",
            "exp": now + 60,
            "iat": now,
        },
    )
    with pytest.raises(ValueError, match="audience"):
        verifier.verify(token)


def test_verifier_rejects_wrong_issuer(rsa_keypair: rsa.RSAPrivateKey, fake_jwk_client: Any) -> None:
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    now = int(time.time())
    token = _sign(
        rsa_keypair,
        {
            "iss": "https://evil.example.com/",
            "aud": "api://app",
            "sub": "user-1",
            "exp": now + 60,
            "iat": now,
        },
    )
    with pytest.raises(ValueError, match="issuer"):
        verifier.verify(token)


def test_verifier_inherits_rbac_permission_methods(rsa_keypair: rsa.RSAPrivateKey, fake_jwk_client: Any) -> None:
    """EntraTokenVerifier extends RBACManager — verify+authorize in one object."""
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
        roles={"admin": ["*"], "viewer": ["agents.list"]},
    )
    assert isinstance(verifier, RBACManager)

    now = int(time.time())
    token = _sign(
        rsa_keypair,
        {
            "iss": _entra_v2_iss("t"),
            "aud": "api://app",
            "sub": "user-1",
            "roles": ["admin"],
            "exp": now + 60,
            "iat": now,
        },
    )
    claims = verifier.validate_token(token)
    assert verifier.has_permission(claims, "anything.at.all") is True
    assert verifier.get_user_id(claims) == "user-1"
    assert verifier.get_roles(claims) == ["admin"]


def test_verify_alias_matches_validate_token(rsa_keypair: rsa.RSAPrivateKey, fake_jwk_client: Any) -> None:
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    now = int(time.time())
    token = _sign(
        rsa_keypair,
        {
            "iss": _entra_v2_iss("t"),
            "aud": "api://app",
            "sub": "user-1",
            "exp": now + 60,
            "iat": now,
        },
    )
    assert verifier.verify(token) == verifier.validate_token(token)


def test_rbac_manager_without_secret_rejects_create_token() -> None:
    rbac = RBACManager()
    with pytest.raises(ValueError, match="jwt_secret"):
        rbac.create_token(user_id="u", roles=["admin"])


def test_rbac_manager_without_secret_rejects_validate_token() -> None:
    rbac = RBACManager()
    with pytest.raises(ValueError, match="jwt_secret"):
        rbac.validate_token("any.token")


def test_rbac_manager_without_secret_still_checks_permissions() -> None:
    """Permission checking is decoupled from token validation."""
    rbac = RBACManager(roles={"admin": ["*"]})
    assert rbac.has_permission({"roles": ["admin"]}, "tools.execute") is True
    assert rbac.has_permission({"roles": ["viewer"]}, "tools.execute") is False


def test_verifier_rejects_token_signed_by_wrong_key(fake_jwk_client: Any) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = EntraTokenVerifier(
        tenant_id="t",
        audience="api://app",
        jwk_client=fake_jwk_client,
    )
    now = int(time.time())
    token = _sign(
        other_key,
        {
            "iss": _entra_v2_iss("t"),
            "aud": "api://app",
            "sub": "user-1",
            "exp": now + 60,
            "iat": now,
        },
    )
    with pytest.raises(ValueError):
        verifier.verify(token)


# --- EntraOBOClient ---------------------------------------------------------


class _FakeMSALApp:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def acquire_token_on_behalf_of(self, user_assertion: str, scopes: list[str]) -> dict[str, Any]:
        self.calls.append({"user_assertion": user_assertion, "scopes": scopes})
        return self._response


def test_obo_exchange_returns_access_token() -> None:
    fake_app = _FakeMSALApp({"access_token": "downstream-token-123", "expires_in": 3600})
    captured_assertion: list[str] = []

    def fake_factory(assertion: str) -> _FakeMSALApp:
        captured_assertion.append(assertion)
        return fake_app

    client = EntraOBOClient(
        tenant_id="tenant-guid",
        client_id="app-client-id",
        assertion_provider=lambda: "uami-federated-assertion",
        msal_app_factory=fake_factory,
    )
    token = client.exchange("user-bearer-token", ["https://graph.microsoft.com/Sites.Read.All"])

    assert token == "downstream-token-123"
    assert fake_app.calls == [
        {
            "user_assertion": "user-bearer-token",
            "scopes": ["https://graph.microsoft.com/Sites.Read.All"],
        }
    ]
    assert captured_assertion == ["uami-federated-assertion"]


def test_obo_exchange_raises_on_msal_error() -> None:
    fake_app = _FakeMSALApp({"error": "invalid_grant", "error_description": "AADSTS70008: token expired"})
    client = EntraOBOClient(
        tenant_id="t",
        client_id="c",
        assertion_provider=lambda: "x",
        msal_app_factory=lambda _assertion: fake_app,
    )
    with pytest.raises(ValueError, match="AADSTS70008"):
        client.exchange("user-token", ["scope"])


def test_entra_config_defaults_to_none() -> None:
    cfg = FireflyAgenticConfig()
    assert cfg.entra_tenant_id is None
    assert cfg.entra_client_id is None
    assert cfg.entra_audience is None
    assert cfg.entra_obo_scopes == []


def test_entra_config_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREFLY_AGENTIC_ENTRA_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("FIREFLY_AGENTIC_ENTRA_CLIENT_ID", "client-guid")
    monkeypatch.setenv("FIREFLY_AGENTIC_ENTRA_AUDIENCE", "api://my-server")
    monkeypatch.setenv(
        "FIREFLY_AGENTIC_ENTRA_OBO_SCOPES",
        '["https://graph.microsoft.com/.default"]',
    )
    cfg = FireflyAgenticConfig()
    assert cfg.entra_tenant_id == "tenant-guid"
    assert cfg.entra_client_id == "client-guid"
    assert cfg.entra_audience == "api://my-server"
    assert cfg.entra_obo_scopes == ["https://graph.microsoft.com/.default"]


def test_obo_exchange_calls_assertion_provider_each_call() -> None:
    """Federated assertions are short-lived; provider must be re-invoked per
    exchange so the assertion is fresh."""
    fake_app = _FakeMSALApp({"access_token": "tok"})
    counter = {"n": 0}

    def provider() -> str:
        counter["n"] += 1
        return f"assertion-{counter['n']}"

    client = EntraOBOClient(
        tenant_id="t",
        client_id="c",
        assertion_provider=provider,
        msal_app_factory=lambda _assertion: fake_app,
    )
    client.exchange("u", ["s"])
    client.exchange("u", ["s"])

    assert counter["n"] == 2
