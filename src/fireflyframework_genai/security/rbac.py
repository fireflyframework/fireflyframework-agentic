# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Role-Based Access Control (RBAC) with JWT authentication.

This module provides a production-ready RBAC system with:
- JWT token validation
- Role and permission management
- Multi-tenant support
- Decorator-based permission checking

Example:
    Basic RBAC setup::

        from fireflyframework_genai.security.rbac import RBACManager, require_permission

        rbac = RBACManager(jwt_secret="your-secret-key")

        # Validate token and check permissions
        @require_permission("agents.execute", rbac=rbac)
        async def run_agent(token: str, agent_name: str):
            # This function only runs if the user has the permission
            return await agent.run(...)

    Multi-tenant RBAC::

        rbac = RBACManager(jwt_secret="secret", multi_tenant=True)

        # Token includes tenant_id
        token = rbac.create_token(
            user_id="user123",
            roles=["agent_runner"],
            tenant_id="acme_corp"
        )
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class RBACManager:
    """Role-Based Access Control manager with JWT support.

    Manages user roles, permissions, and JWT token validation for
    securing agent execution and API access in production deployments.

    Parameters:
        jwt_secret: Secret key for JWT token signing and verification.
        jwt_algorithm: JWT algorithm (default: HS256).
        token_expiry_hours: Hours until tokens expire.
        multi_tenant: Whether to enforce tenant isolation.
        roles: Role-to-permissions mapping.

    Example::

        rbac = RBACManager(
            jwt_secret="my-secret-key",
            roles={
                "admin": ["*"],
                "agent_runner": ["agents.execute", "agents.list"],
                "viewer": ["agents.list"],
            }
        )

        # Create token
        token = rbac.create_token(user_id="user123", roles=["agent_runner"])

        # Validate and extract claims
        claims = rbac.validate_token(token)

        # Check permission
        if rbac.has_permission(claims, "agents.execute"):
            # Allow execution
            pass
    """

    def __init__(
        self,
        jwt_secret: str,
        *,
        jwt_algorithm: str = "HS256",
        token_expiry_hours: int = 24,
        multi_tenant: bool = False,
        roles: dict[str, list[str]] | None = None,
    ) -> None:
        self._jwt_secret = jwt_secret
        self._jwt_algorithm = jwt_algorithm
        self._token_expiry_hours = token_expiry_hours
        self._multi_tenant = multi_tenant

        # Default role-to-permissions mapping
        self._roles = roles or {
            "admin": ["*"],  # Wildcard: all permissions
            "agent_runner": ["agents.execute", "agents.list", "tools.execute"],
            "agent_viewer": ["agents.list"],
            "pipeline_runner": ["pipelines.execute", "pipelines.list"],
        }

    def create_token(
        self,
        user_id: str,
        roles: list[str],
        *,
        tenant_id: str | None = None,
        custom_claims: dict[str, Any] | None = None,
    ) -> str:
        """Create a JWT token with user claims.

        Args:
            user_id: Unique user identifier.
            roles: List of role names assigned to the user.
            tenant_id: Optional tenant ID for multi-tenant deployments.
            custom_claims: Additional custom claims to include in the token.

        Returns:
            Signed JWT token string.

        Raises:
            ImportError: If PyJWT is not installed.
        """
        try:
            import jwt
        except ImportError as exc:
            raise ImportError(
                "JWT support requires 'pyjwt'. Install with: pip install fireflyframework-genai[security]"
            ) from exc

        now = datetime.now(UTC)
        expiry = now + timedelta(hours=self._token_expiry_hours)

        payload = {
            "sub": user_id,
            "roles": roles,
            "iat": now,
            "exp": expiry,
        }

        if self._multi_tenant and tenant_id:
            payload["tenant_id"] = tenant_id
        elif self._multi_tenant and not tenant_id:
            raise ValueError("tenant_id is required when multi_tenant is enabled")

        if custom_claims:
            payload.update(custom_claims)

        token = jwt.encode(payload, self._jwt_secret, algorithm=self._jwt_algorithm)
        return token

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a JWT token and return its claims.

        Args:
            token: JWT token string.

        Returns:
            Dictionary of token claims (user_id, roles, etc.).

        Raises:
            ValueError: If token is invalid or expired.
            ImportError: If PyJWT is not installed.
        """
        try:
            import jwt
        except ImportError as exc:
            raise ImportError(
                "JWT support requires 'pyjwt'. Install with: pip install fireflyframework-genai[security]"
            ) from exc

        try:
            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._jwt_algorithm],
            )
            return payload
        except jwt.ExpiredSignatureError as exc:
            raise ValueError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise ValueError(f"Invalid token: {exc}") from exc

    def has_permission(self, claims: dict[str, Any], permission: str) -> bool:
        """Check if the user has a specific permission.

        Args:
            claims: Token claims from validate_token().
            permission: Permission string to check (e.g., "agents.execute").

        Returns:
            True if user has the permission, False otherwise.
        """
        roles = claims.get("roles", [])

        for role in roles:
            permissions = self._roles.get(role, [])

            # Wildcard permission grants everything
            if "*" in permissions:
                return True

            # Exact match
            if permission in permissions:
                return True

            # Prefix match (e.g., "agents.*" grants "agents.execute")
            for perm in permissions:
                if perm.endswith(".*"):
                    prefix = perm[:-2]
                    if permission.startswith(f"{prefix}."):
                        return True

        return False

    def check_tenant_access(
        self,
        claims: dict[str, Any],
        tenant_id: str,
    ) -> bool:
        """Check if the user has access to a specific tenant.

        Args:
            claims: Token claims from validate_token().
            tenant_id: Tenant ID to check access for.

        Returns:
            True if user has access, False otherwise.
        """
        if not self._multi_tenant:
            return True  # No tenant isolation

        token_tenant = claims.get("tenant_id")
        return token_tenant == tenant_id

    def get_user_id(self, claims: dict[str, Any]) -> str:
        """Extract user ID from token claims.

        Args:
            claims: Token claims from validate_token().

        Returns:
            User ID string.
        """
        return claims.get("sub", "")

    def get_roles(self, claims: dict[str, Any]) -> list[str]:
        """Extract roles from token claims.

        Args:
            claims: Token claims from validate_token().

        Returns:
            List of role names.
        """
        return claims.get("roles", [])

    def get_permissions(self, claims: dict[str, Any]) -> list[str]:
        """Get all permissions for the user based on their roles.

        Args:
            claims: Token claims from validate_token().

        Returns:
            List of all permissions granted to the user.
        """
        roles = self.get_roles(claims)
        permissions = set()

        for role in roles:
            role_perms = self._roles.get(role, [])
            permissions.update(role_perms)

        return list(permissions)


def require_permission(
    permission: str,
    *,
    rbac: RBACManager | None = None,
    token_param: str = "token",
) -> Callable:
    """Decorator to require a specific permission for a function.

    Args:
        permission: Required permission string.
        rbac: RBACManager instance. If None, uses default from config.
        token_param: Name of the function parameter containing the JWT token.

    Returns:
        Decorator function.

    Example::

        @require_permission("agents.execute")
        async def run_agent(token: str, agent_name: str, prompt: str):
            # This only runs if token has "agents.execute" permission
            return await agent.run(prompt)

        # Usage
        try:
            result = await run_agent(
                token="eyJ...",
                agent_name="my_agent",
                prompt="Hello"
            )
        except ValueError:
            print("Permission denied or invalid token")
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get RBAC manager
            manager = rbac or _get_default_rbac()

            if manager is None:
                raise ValueError(
                    "No RBAC manager configured. Set FIREFLY_GENAI_RBAC_ENABLED=true "
                    "and FIREFLY_GENAI_RBAC_JWT_SECRET in environment."
                )

            # Extract token from args/kwargs using signature binding
            import inspect as _inspect

            try:
                sig = _inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                token = bound.arguments.get(token_param)
            except TypeError as exc:
                raise ValueError(f"Missing required parameter: {token_param}") from exc
            if not token:
                raise ValueError(f"Missing required parameter: {token_param}")

            # Validate token and check permission
            try:
                claims = manager.validate_token(token)
            except ValueError as exc:
                logger.warning("Token validation failed: %s", exc)
                raise

            if not manager.has_permission(claims, permission):
                user_id = manager.get_user_id(claims)
                roles = manager.get_roles(claims)
                logger.warning(
                    "Permission denied: user=%s, roles=%s, required=%s",
                    user_id,
                    roles,
                    permission,
                )
                raise ValueError(f"Permission denied: {permission}")

            # Call the original function
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get RBAC manager
            manager = rbac or _get_default_rbac()

            if manager is None:
                raise ValueError(
                    "No RBAC manager configured. Set FIREFLY_GENAI_RBAC_ENABLED=true "
                    "and FIREFLY_GENAI_RBAC_JWT_SECRET in environment."
                )

            # Extract token from args/kwargs
            import inspect as _inspect

            try:
                sig = _inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                token = bound.arguments.get(token_param)
            except TypeError as exc:
                raise ValueError(f"Missing required parameter: {token_param}") from exc
            if not token:
                raise ValueError(f"Missing required parameter: {token_param}")

            # Validate token and check permission
            try:
                claims = manager.validate_token(token)
            except ValueError as exc:
                logger.warning("Token validation failed: %s", exc)
                raise

            if not manager.has_permission(claims, permission):
                user_id = manager.get_user_id(claims)
                roles = manager.get_roles(claims)
                logger.warning(
                    "Permission denied: user=%s, roles=%s, required=%s",
                    user_id,
                    roles,
                    permission,
                )
                raise ValueError(f"Permission denied: {permission}")

            # Call the original function
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def _get_default_rbac() -> RBACManager | None:
    """Get the default RBAC manager from configuration."""
    try:
        from fireflyframework_genai.config import get_config

        cfg = get_config()
        if not cfg.rbac_enabled or not cfg.rbac_jwt_secret:
            return None

        return RBACManager(
            jwt_secret=cfg.rbac_jwt_secret,
            multi_tenant=cfg.rbac_multi_tenant,
        )
    except Exception:  # noqa: BLE001
        return None


# Module-level default instance
default_rbac: RBACManager | None = _get_default_rbac()
