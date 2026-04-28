"""Tests for security/output_guard.py — OutputGuard scanning and OutputGuardMiddleware."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.agents.builtin_middleware import (
    OutputGuardError,
    OutputGuardMiddleware,
)
from fireflyframework_agentic.agents.middleware import MiddlewareContext
from fireflyframework_agentic.security.output_guard import OutputGuard, default_output_guard

# -- OutputGuard core --------------------------------------------------------


class TestOutputGuard:
    def test_detect_ssn(self):
        result = default_output_guard.scan("My SSN is 123-45-6789")
        assert result.safe is False
        assert result.pii_detected is True

    def test_detect_email(self):
        result = default_output_guard.scan("Contact me at user@example.com")
        assert result.safe is False
        assert result.pii_detected is True

    def test_detect_credit_card(self):
        result = default_output_guard.scan("Card: 4111-1111-1111-1111")
        assert result.safe is False
        assert result.pii_detected is True

    def test_detect_api_key(self):
        result = default_output_guard.scan("Use key sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234")
        assert result.safe is False
        assert result.secrets_detected is True

    def test_detect_aws_key(self):
        result = default_output_guard.scan("AKIAIOSFODNN7EXAMPLE")
        assert result.safe is False
        assert result.secrets_detected is True

    def test_detect_script_tag(self):
        result = default_output_guard.scan("<script>alert('xss')</script>")
        assert result.safe is False
        assert result.harmful_detected is True

    def test_safe_output(self):
        result = default_output_guard.scan("The weather today is sunny and warm.")
        assert result.safe is True
        assert result.pii_detected is False
        assert result.secrets_detected is False
        assert result.harmful_detected is False


# -- Edge cases ---------------------------------------------------------------


class TestOutputGuardEdgeCases:
    def test_empty_string(self):
        result = default_output_guard.scan("")
        assert result.safe is True

    def test_max_output_length(self):
        guard = OutputGuard(max_output_length=10)
        result = guard.scan("a" * 100)
        assert result.safe is False
        assert "maximum length" in result.reason

    def test_sanitise_mode_redacts(self):
        guard = OutputGuard(sanitise=True)
        result = guard.scan("My SSN is 123-45-6789")
        assert result.safe is False
        assert result.sanitised_output is not None
        assert "123-45-6789" not in result.sanitised_output
        assert "[REDACTED]" in result.sanitised_output

    def test_valid_ip_detected(self):
        result = default_output_guard.scan("Server at 192.168.1.1 is down")
        assert result.safe is False
        assert result.pii_detected is True

    def test_version_number_not_flagged_as_ip(self):
        """Version strings like 1.2.3.400 should not match IP pattern."""
        result = default_output_guard.scan("Using version 1.2.3.400 of the library")
        # 400 > 255, so the tightened IP pattern should not match
        assert result.pii_detected is False

    def test_multiline_xss_detected(self):
        result = default_output_guard.scan('<script>\nalert("xss")\n</script>')
        assert result.safe is False
        assert result.harmful_detected is True

    def test_deny_patterns(self):
        guard = OutputGuard(
            scan_pii=False,
            scan_secrets=False,
            scan_harmful=False,
            deny_patterns=["CONFIDENTIAL"],
        )
        result = guard.scan("This is CONFIDENTIAL data")
        assert result.safe is False


# -- OutputGuardMiddleware ----------------------------------------------------


class TestOutputGuardMiddleware:
    async def test_blocks_pii(self):
        mw = OutputGuardMiddleware()
        ctx = MiddlewareContext(agent_name="test", prompt="hi")
        with pytest.raises(OutputGuardError, match="Output blocked"):
            await mw.after_run(ctx, "My SSN is 123-45-6789")

    async def test_allows_safe(self):
        mw = OutputGuardMiddleware()
        ctx = MiddlewareContext(agent_name="test", prompt="hi")
        result = await mw.after_run(ctx, "Hello, world!")
        assert result == "Hello, world!"

    async def test_sanitise_mode(self):
        mw = OutputGuardMiddleware(sanitise=True)
        ctx = MiddlewareContext(agent_name="test", prompt="hi")
        result = await mw.after_run(ctx, "My SSN is 123-45-6789")
        assert "123-45-6789" not in result
        assert "[REDACTED]" in result
