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

:class:`EntraTokenVerifier` extends :class:`~fireflyframework_agentic.security.rbac.RBACManager`,
overriding :meth:`~fireflyframework_agentic.security.rbac.RBACManager.validate_token`
with RS256 + JWKS validation. All permission/role/tenant methods
(``has_permission``, ``get_user_id``, ``check_tenant_access``, …) are inherited
unchanged, so Entra-issued claims plug directly into the existing authorization
machinery.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import jwt
from azure.identity import DefaultAzureCredential
from jwt import PyJWKClient
from msal import ConfidentialClientApplication

from fireflyframework_agentic.security.rbac import RBACManager

logger = logging.getLogger(__name__)

_FEDERATION_AUDIENCE = "api://AzureADTokenExchange"


class _SigningKeyResolver(Protocol):
    """Minimal interface a JWKS client must satisfy.

    PyJWKClient implements this; tests inject a fake.
    """

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class EntraTokenVerifier(RBACManager):
    """Verify Entra ID-issued RS256 JWTs against the tenant's JWKS.

    Subclass of :class:`RBACManager` — replaces HS256 + shared secret
    validation with RS256 + JWKS. Inherits ``has_permission``,
    ``check_tenant_access``, ``get_user_id``, ``get_roles``, ``get_permissions``
    so callers can compose verification and authorization in one object::

        verifier = EntraTokenVerifier(tenant_id="…", audience="api://app",
                                      roles={"admin": ["*"]})
        claims = verifier.validate_token(bearer_token)
        if not verifier.has_permission(claims, "tools.execute"):
            raise PermissionError

    Parameters:
        tenant_id: Entra tenant (directory) GUID.
        audience: Expected ``aud`` claim — typically ``api://{client_id}`` of
            the resource (i.e. this server's app registration).
        jwk_client: Override the default :class:`jwt.PyJWKClient`. Tests inject
            a fake; production deployments may inject one with custom HTTP
            settings.
        roles: Role-to-permissions mapping, forwarded to
            :class:`RBACManager`. The roles used here typically come from
            Entra group / app role claims.
        multi_tenant: Forwarded to :class:`RBACManager` for tenant-isolation
            checks via ``check_tenant_access``.
    """

    def __init__(
        self,
        tenant_id: str,
        audience: str,
        *,
        jwk_client: _SigningKeyResolver | None = None,
        roles: dict[str, list[str]] | None = None,
        multi_tenant: bool = False,
    ) -> None:
        super().__init__(jwt_secret=None, multi_tenant=multi_tenant, roles=roles)
        self._tenant_id = tenant_id
        self._audience = audience
        self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._jwk_client: _SigningKeyResolver = jwk_client or PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
            cache_keys=True,
            lifespan=3600,
        )

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate ``token`` and return its claims.

        Overrides :meth:`RBACManager.validate_token` with RS256 + JWKS
        verification (signature, expiry, audience, issuer). Raises
        ``ValueError`` on any failure.
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

    # Entra-friendly alias.
    def verify(self, token: str) -> dict[str, Any]:
        """Alias for :meth:`validate_token` — matches Entra/OAuth nomenclature."""
        return self.validate_token(token)


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

    Uses the OAuth 2.0 On-Behalf-Of flow. The server's identity to Entra is
    established via **federated client assertion** (workload identity
    federation) — there is no client secret anywhere in the call path.

    Parameters:
        tenant_id: Entra tenant (directory) GUID.
        client_id: This server's app registration client ID.
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
