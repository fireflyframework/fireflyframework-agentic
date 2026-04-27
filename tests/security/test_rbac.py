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

"""Unit tests for RBAC (Role-Based Access Control)."""

from __future__ import annotations

import pytest

# Check if JWT is available
pytest.importorskip("jwt", reason="JWT tests require pyjwt")

from fireflyframework_agentic.security.rbac import RBACManager, require_permission


class TestRBACManager:
    """Test suite for RBACManager."""

    def test_create_and_validate_token(self):
        """Test creating and validating JWT tokens."""
        rbac = RBACManager(jwt_secret="test-secret")

        token = rbac.create_token(user_id="user123", roles=["agent_runner"])
        claims = rbac.validate_token(token)

        assert claims["sub"] == "user123"
        assert claims["roles"] == ["agent_runner"]

    def test_invalid_token(self):
        """Test that invalid tokens are rejected."""
        rbac = RBACManager(jwt_secret="test-secret")

        with pytest.raises(ValueError, match="Invalid token"):
            rbac.validate_token("invalid.token.here")

    def test_wrong_secret(self):
        """Test that tokens signed with different secret are rejected."""
        rbac1 = RBACManager(jwt_secret="secret1")
        rbac2 = RBACManager(jwt_secret="secret2")

        token = rbac1.create_token(user_id="user123", roles=["admin"])

        with pytest.raises(ValueError, match="Invalid token"):
            rbac2.validate_token(token)

    def test_has_permission_exact_match(self):
        """Test permission checking with exact match."""
        rbac = RBACManager(
            jwt_secret="test-secret",
            roles={
                "agent_runner": ["agents.execute", "agents.list"],
                "viewer": ["agents.list"],
            },
        )

        token = rbac.create_token(user_id="user123", roles=["agent_runner"])
        claims = rbac.validate_token(token)

        assert rbac.has_permission(claims, "agents.execute")
        assert rbac.has_permission(claims, "agents.list")
        assert not rbac.has_permission(claims, "pipelines.execute")

    def test_has_permission_wildcard(self):
        """Test that wildcard permission grants everything."""
        rbac = RBACManager(jwt_secret="test-secret", roles={"admin": ["*"]})

        token = rbac.create_token(user_id="admin", roles=["admin"])
        claims = rbac.validate_token(token)

        assert rbac.has_permission(claims, "agents.execute")
        assert rbac.has_permission(claims, "anything.anything")
        assert rbac.has_permission(claims, "foo.bar.baz")

    def test_has_permission_prefix_match(self):
        """Test permission checking with prefix wildcard."""
        rbac = RBACManager(jwt_secret="test-secret", roles={"agent_admin": ["agents.*"]})

        token = rbac.create_token(user_id="user123", roles=["agent_admin"])
        claims = rbac.validate_token(token)

        assert rbac.has_permission(claims, "agents.execute")
        assert rbac.has_permission(claims, "agents.list")
        assert rbac.has_permission(claims, "agents.delete")
        assert not rbac.has_permission(claims, "pipelines.execute")

    def test_has_permission_no_role(self):
        """Test that users without matching roles have no permissions."""
        rbac = RBACManager(jwt_secret="test-secret", roles={"admin": ["*"]})

        token = rbac.create_token(user_id="user123", roles=["unknown_role"])
        claims = rbac.validate_token(token)

        assert not rbac.has_permission(claims, "agents.execute")

    def test_multi_tenant_token(self):
        """Test multi-tenant token creation and validation."""
        rbac = RBACManager(jwt_secret="test-secret", multi_tenant=True)

        token = rbac.create_token(user_id="user123", roles=["agent_runner"], tenant_id="acme_corp")
        claims = rbac.validate_token(token)

        assert claims["tenant_id"] == "acme_corp"

    def test_multi_tenant_requires_tenant_id(self):
        """Test that multi-tenant mode requires tenant_id."""
        rbac = RBACManager(jwt_secret="test-secret", multi_tenant=True)

        with pytest.raises(ValueError, match="tenant_id is required"):
            rbac.create_token(user_id="user123", roles=["admin"])

    def test_check_tenant_access(self):
        """Test tenant access checking."""
        rbac = RBACManager(jwt_secret="test-secret", multi_tenant=True)

        token = rbac.create_token(user_id="user123", roles=["admin"], tenant_id="tenant_a")
        claims = rbac.validate_token(token)

        assert rbac.check_tenant_access(claims, "tenant_a")
        assert not rbac.check_tenant_access(claims, "tenant_b")

    def test_custom_claims(self):
        """Test adding custom claims to tokens."""
        rbac = RBACManager(jwt_secret="test-secret")

        token = rbac.create_token(
            user_id="user123", roles=["admin"], custom_claims={"department": "engineering", "level": 5}
        )
        claims = rbac.validate_token(token)

        assert claims["department"] == "engineering"
        assert claims["level"] == 5

    def test_get_user_id(self):
        """Test extracting user ID from claims."""
        rbac = RBACManager(jwt_secret="test-secret")

        token = rbac.create_token(user_id="user123", roles=["admin"])
        claims = rbac.validate_token(token)

        assert rbac.get_user_id(claims) == "user123"

    def test_get_roles(self):
        """Test extracting roles from claims."""
        rbac = RBACManager(jwt_secret="test-secret")

        token = rbac.create_token(user_id="user123", roles=["admin", "agent_runner"])
        claims = rbac.validate_token(token)

        assert rbac.get_roles(claims) == ["admin", "agent_runner"]

    def test_get_permissions(self):
        """Test getting all permissions for a user."""
        rbac = RBACManager(
            jwt_secret="test-secret",
            roles={
                "agent_runner": ["agents.execute", "agents.list"],
                "pipeline_runner": ["pipelines.execute"],
            },
        )

        token = rbac.create_token(user_id="user123", roles=["agent_runner", "pipeline_runner"])
        claims = rbac.validate_token(token)

        permissions = rbac.get_permissions(claims)
        assert "agents.execute" in permissions
        assert "agents.list" in permissions
        assert "pipelines.execute" in permissions


@pytest.mark.asyncio
class TestRequirePermissionDecorator:
    """Test suite for @require_permission decorator."""

    async def test_decorator_allows_with_permission(self):
        """Test that decorator allows function when permission is granted."""
        rbac = RBACManager(jwt_secret="test-secret", roles={"agent_runner": ["agents.execute"]})

        @require_permission("agents.execute", rbac=rbac)
        async def protected_function(token: str, data: str) -> str:
            return f"Success: {data}"

        token = rbac.create_token(user_id="user123", roles=["agent_runner"])
        result = await protected_function(token=token, data="test")

        assert result == "Success: test"

    async def test_decorator_denies_without_permission(self):
        """Test that decorator blocks function when permission is missing."""
        rbac = RBACManager(jwt_secret="test-secret", roles={"viewer": ["agents.list"]})

        @require_permission("agents.execute", rbac=rbac)
        async def protected_function(token: str, data: str) -> str:
            return f"Success: {data}"

        token = rbac.create_token(user_id="user123", roles=["viewer"])

        with pytest.raises(ValueError, match="Permission denied"):
            await protected_function(token=token, data="test")

    async def test_decorator_rejects_invalid_token(self):
        """Test that decorator rejects invalid tokens."""
        rbac = RBACManager(jwt_secret="test-secret")

        @require_permission("agents.execute", rbac=rbac)
        async def protected_function(token: str) -> str:
            return "Success"

        with pytest.raises(ValueError, match="Invalid token"):
            await protected_function(token="invalid.token")

    async def test_decorator_requires_token_parameter(self):
        """Test that decorator requires token parameter."""
        rbac = RBACManager(jwt_secret="test-secret")

        @require_permission("agents.execute", rbac=rbac)
        async def protected_function(token: str) -> str:
            return "Success"

        with pytest.raises(ValueError, match="Missing required parameter: token"):
            await protected_function()

    def test_decorator_with_sync_function(self):
        """Test that decorator works with synchronous functions."""
        rbac = RBACManager(jwt_secret="test-secret", roles={"admin": ["*"]})

        @require_permission("agents.execute", rbac=rbac)
        def protected_sync_function(token: str, data: str) -> str:
            return f"Sync success: {data}"

        token = rbac.create_token(user_id="admin", roles=["admin"])
        result = protected_sync_function(token=token, data="test")

        assert result == "Sync success: test"
