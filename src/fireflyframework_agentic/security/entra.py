# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Entra ID (Azure AD) token verification and OBO exchange.

Validates RS256 JWTs issued by Entra ID against the published JWKS, and
exchanges incoming user tokens for downstream Graph/SharePoint tokens via the
OAuth 2.0 On-Behalf-Of flow.

The framework's existing
:class:`fireflyframework_agentic.security.rbac.RBACManager` covers HS256 with a
shared secret; this module is the parallel for asymmetric, externally-issued
tokens (Entra ID).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import jwt
from azure.identity import DefaultAzureCredential
from jwt import PyJWKClient
from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)

_FEDERATION_AUDIENCE = "api://AzureADTokenExchange"


class _SigningKeyResolver(Protocol):
    """Minimal interface a JWKS client must satisfy.

    PyJWKClient implements this; tests inject a fake.
    """

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class EntraTokenVerifier:
    """Verify Entra ID-issued RS256 JWTs against the tenant's JWKS.

    The verifier validates signature, expiry, audience, and issuer. JWKS keys
    are fetched from the v2.0 OIDC discovery endpoint and cached by the
    underlying :class:`jwt.PyJWKClient`.

    Parameters:
        tenant_id: Entra tenant (directory) GUID.
        audience: Expected ``aud`` claim — typically ``api://{client_id}`` of
            the resource (i.e. this MCP server's app registration).
        jwk_client: Override the default :class:`jwt.PyJWKClient`. Tests inject
            a fake; production deployments may inject one with custom HTTP
            settings.
    """

    def __init__(
        self,
        tenant_id: str,
        audience: str,
        *,
        jwk_client: _SigningKeyResolver | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._audience = audience
        self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._jwk_client: _SigningKeyResolver = jwk_client or PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
            cache_keys=True,
            lifespan=3600,
        )

    def verify(self, token: str) -> dict[str, Any]:
        """Validate ``token`` and return its claims.

        Raises ``ValueError`` on any failure (bad signature, expired, wrong
        audience/issuer, malformed token, JWKS lookup failure).
        """
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        except jwt.InvalidTokenError as exc:
            raise ValueError(f"Invalid token: {exc}") from exc
        except Exception as exc:
            raise ValueError(f"Invalid token: {exc}") from exc

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
            return claims
        except jwt.ExpiredSignatureError as exc:
            raise ValueError("Token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise ValueError(f"Invalid audience: expected {self._audience}") from exc
        except jwt.InvalidIssuerError as exc:
            raise ValueError(f"Invalid issuer: expected {self._issuer}") from exc
        except jwt.InvalidTokenError as exc:
            raise ValueError(f"Invalid token: {exc}") from exc


def _default_assertion_provider() -> str:
    """Mint a federated client assertion via the local Managed Identity.

    The assertion is a JWT issued by Azure IMDS with audience
    ``api://AzureADTokenExchange``. The Entra app registration trusts this UAMI
    via a federated identity credential, so no client secret is needed.
    """
    credential = DefaultAzureCredential()
    return credential.get_token(f"{_FEDERATION_AUDIENCE}/.default").token


class EntraOBOClient:
    """Exchange incoming user tokens for downstream Graph/SharePoint tokens.

    Uses the OAuth 2.0 On-Behalf-Of flow. The MCP server's identity to Entra
    is established via **federated client assertion** (workload identity
    federation) — there is no client secret anywhere in the call path.

    Parameters:
        tenant_id: Entra tenant (directory) GUID.
        client_id: The MCP server's app registration client ID.
        assertion_provider: Returns a federated client assertion JWT. Defaults
            to :func:`_default_assertion_provider` which uses
            :class:`azure.identity.DefaultAzureCredential`. Tests inject a
            stub.
        msal_app_factory: Builds the MSAL confidential client given an
            assertion. Defaults to a real
            :class:`msal.ConfidentialClientApplication`. Tests inject a stub.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        *,
        assertion_provider: Callable[[], str] | None = None,
        msal_app_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._assertion_provider = assertion_provider or _default_assertion_provider
        self._msal_app_factory = msal_app_factory or self._build_msal_app

    def _build_msal_app(self, assertion: str) -> ConfidentialClientApplication:
        return ConfidentialClientApplication(
            client_id=self._client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            client_credential={"client_assertion": assertion},
        )

    def exchange(self, user_token: str, scopes: list[str]) -> str:
        """Exchange ``user_token`` for a downstream access token.

        Returns the access token string. Raises ``ValueError`` if the
        federated assertion cannot be minted or if Entra rejects the
        exchange.
        """
        assertion = self._assertion_provider()
        app = self._msal_app_factory(assertion)
        result = app.acquire_token_on_behalf_of(
            user_assertion=user_token,
            scopes=scopes,
        )
        if "access_token" not in result:
            error = result.get("error_description") or result.get("error", "unknown")
            raise ValueError(f"OBO exchange failed: {error}")
        return result["access_token"]
