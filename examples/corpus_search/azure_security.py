# Copyright 2026 Firefly Software Foundation
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
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from fireflyframework_agentic.exposure.mcp.auth import OAuthMetadata

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

    def get_signing_key_from_jwt(self, token: str) -> Any:
        raise NotImplementedError


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
        audience: Expected ``aud`` claim. For Entra v2.0 access tokens (which
            this verifier requires via the ``.../v2.0`` issuer pin) this is the
            bare ``client_id`` GUID, not ``api://{client_id}``.
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


# ----------------------------------------------------------------------------
# OAuth / Entra ID factories for firefly-mcp-http
# ----------------------------------------------------------------------------
#
# These two factories are the defaults wired into the framework's
# ``_install_oauth_auth`` helper via ``FIREFLY_MCP_VERIFIER_FACTORY`` and
# ``FIREFLY_MCP_METADATA_FACTORY``. They translate three operator-supplied
# env vars (``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``,
# ``FIREFLY_MCP_PUBLIC_URL``) into the provider-agnostic OAuth types the
# framework understands. Operators on a different IdP swap these for
# their own callables — the framework code stays unchanged.


def build_entra_verifier() -> EntraTokenVerifier:
    """Default verifier factory for ``FIREFLY_MCP_VERIFIER_FACTORY``.

    Reads ``AZURE_TENANT_ID`` and ``AZURE_CLIENT_ID`` from the
    environment. Raises ``RuntimeError`` with a clear message if either
    is missing — the alternative (a confusing JWT validation failure on
    first request) makes ops debugging much harder.
    """
    import os

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    if not tenant or not client:
        raise RuntimeError("build_entra_verifier requires AZURE_TENANT_ID and AZURE_CLIENT_ID")
    # v2 access tokens carry the bare client GUID in `aud` (not `api://<guid>`).
    # The verifier pins the issuer to `.../v2.0`, so only v2 tokens can pass —
    # matching audience to the bare client keeps both checks consistent.
    return EntraTokenVerifier(tenant_id=tenant, audience=client)


def build_entra_metadata() -> OAuthMetadata:
    """Default metadata factory for ``FIREFLY_MCP_METADATA_FACTORY``.

    Reads ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``, and
    ``FIREFLY_MCP_PUBLIC_URL`` (the canonical https URL of this MCP
    server, no trailing slash) to populate the ``OAuthMetadata`` doc
    returned at ``/.well-known/*``.
    """
    import os

    from fireflyframework_agentic.exposure.mcp.auth import OAuthMetadata

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    host = os.environ.get("FIREFLY_MCP_PUBLIC_URL", "").rstrip("/")
    if not tenant or not client or not host:
        raise RuntimeError("build_entra_metadata requires AZURE_TENANT_ID, AZURE_CLIENT_ID, and FIREFLY_MCP_PUBLIC_URL")
    base = f"https://login.microsoftonline.com/{tenant}"
    # ``issuer`` is the URL the MCP client uses to discover the auth server
    # (RFC 8414): it MUST match the URL where the metadata is served, i.e.
    # our own host. Entra's actual issuer URL is hardcoded inside
    # ``EntraTokenVerifier`` and used only for JWT ``iss`` validation, so
    # advertising our own URL here does not affect token verification.
    # We point ``authorization_endpoint`` / ``token_endpoint`` / ``jwks_uri``
    # at Entra so the client runs the OAuth flow against the real IdP —
    # we are not acting as an authorization-server proxy.
    # ``resource`` is advertised at ``/.well-known/oauth-protected-resource``
    # and MCP clients forward it to Entra as the RFC 8707 ``resource=``
    # parameter on the token request. Two opposing constraints apply:
    #   * The MCP SDK (Claude Code) validates the metadata's ``resource``
    #     against the server URL and accepts only an exact match or the
    #     URL's origin — using ``api://<client>`` trips
    #     "Protected resource ... does not match expected ... (or origin)".
    #   * Entra requires the value to match an App Registration
    #     ``identifierUri``. It accepts ``https://<host>`` origins on
    #     verified-or-Microsoft-owned domains, but rejects identifier URIs
    #     that include a path (``/mcp/``) — those return AADSTS9010010 at
    #     the token endpoint.
    # The intersection that both clients accept is the host origin, so the
    # operator must register ``https://<host>`` on the App Reg's
    # ``identifierUris`` and we advertise the same value here.
    return OAuthMetadata(
        issuer=host,
        authorization_endpoint=f"{base}/oauth2/v2.0/authorize",
        token_endpoint=f"{base}/oauth2/v2.0/token",
        jwks_uri=f"{base}/discovery/v2.0/keys",
        resource=host,
        scopes_supported=(f"api://{client}/user_impersonation",),
    )
