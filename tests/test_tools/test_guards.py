"""Tests for tools/guards.py."""

from __future__ import annotations

from fireflyframework_agentic.tools.guards import (
    CompositeGuard,
    RateLimitGuard,
    SandboxGuard,
    ValidationGuard,
)


class TestValidationGuard:
    async def test_passes_when_all_present(self) -> None:
        guard = ValidationGuard(required_keys=["a", "b"])
        result = await guard.check("tool", {"a": 1, "b": 2})
        assert result.passed is True

    async def test_fails_when_missing(self) -> None:
        guard = ValidationGuard(required_keys=["a", "b"])
        result = await guard.check("tool", {"a": 1})
        assert result.passed is False
        assert "b" in (result.reason or "")


class TestRateLimitGuard:
    async def test_allows_under_limit(self) -> None:
        guard = RateLimitGuard(max_calls=3, period_seconds=10)
        for _ in range(3):
            result = await guard.check("tool", {})
            assert result.passed is True

    async def test_blocks_over_limit(self) -> None:
        guard = RateLimitGuard(max_calls=2, period_seconds=10)
        await guard.check("tool", {})
        await guard.check("tool", {})
        result = await guard.check("tool", {})
        assert result.passed is False
        assert "Rate limit" in (result.reason or "")


class TestSandboxGuard:
    async def test_allows_safe_values(self) -> None:
        guard = SandboxGuard(denied_patterns=[r"rm -rf"])
        result = await guard.check("tool", {"cmd": "ls -la"})
        assert result.passed is True

    async def test_blocks_denied_pattern(self) -> None:
        guard = SandboxGuard(denied_patterns=[r"rm -rf"])
        result = await guard.check("tool", {"cmd": "rm -rf /"})
        assert result.passed is False

    async def test_allowed_overrides_denied(self) -> None:
        guard = SandboxGuard(
            denied_patterns=[r"delete"],
            allowed_patterns=[r"delete_temp"],
        )
        result = await guard.check("tool", {"action": "delete_temp"})
        assert result.passed is True


class TestCompositeGuard:
    async def test_all_pass(self) -> None:
        g1 = ValidationGuard(required_keys=["a"])
        g2 = ValidationGuard(required_keys=["b"])
        composite = CompositeGuard([g1, g2])
        result = await composite.check("tool", {"a": 1, "b": 2})
        assert result.passed is True

    async def test_first_failure_short_circuits(self) -> None:
        g1 = ValidationGuard(required_keys=["missing"])
        g2 = ValidationGuard(required_keys=["a"])
        composite = CompositeGuard([g1, g2])
        result = await composite.check("tool", {"a": 1})
        assert result.passed is False
        assert "missing" in (result.reason or "")
