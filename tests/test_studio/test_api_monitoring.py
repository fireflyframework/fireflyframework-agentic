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

"""Tests for the Studio monitoring API endpoints."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.server import create_studio_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a Studio app for testing."""
    return create_studio_app()


@pytest.fixture()
async def client(app):
    """Provide an async httpx client bound to the test app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_usage_tracker():
    """Reset the default usage tracker between tests."""
    from fireflyframework_genai.observability.usage import default_usage_tracker

    default_usage_tracker.reset()
    yield
    default_usage_tracker.reset()


# ---------------------------------------------------------------------------
# GET /api/monitoring/usage
# ---------------------------------------------------------------------------


class TestMonitoringUsage:
    async def test_usage_returns_valid_json_with_expected_fields(self, client: httpx.AsyncClient):
        resp = await client.get("/api/monitoring/usage")
        assert resp.status_code == 200
        body = resp.json()

        # Verify all expected top-level fields are present
        expected_fields = [
            "total_input_tokens",
            "total_output_tokens",
            "total_tokens",
            "total_cost_usd",
            "total_requests",
            "total_latency_ms",
            "record_count",
            "by_agent",
            "by_model",
        ]
        for field in expected_fields:
            assert field in body, f"Missing field: {field}"

    async def test_usage_returns_zeros_when_no_records(self, client: httpx.AsyncClient):
        resp = await client.get("/api/monitoring/usage")
        assert resp.status_code == 200
        body = resp.json()

        assert body["total_input_tokens"] == 0
        assert body["total_output_tokens"] == 0
        assert body["total_tokens"] == 0
        assert body["total_cost_usd"] == 0.0
        assert body["total_requests"] == 0
        assert body["total_latency_ms"] == 0.0
        assert body["record_count"] == 0
        assert body["by_agent"] == {}
        assert body["by_model"] == {}

    async def test_usage_reflects_recorded_data(self, client: httpx.AsyncClient):
        from fireflyframework_genai.observability.usage import (
            UsageRecord,
            default_usage_tracker,
        )

        default_usage_tracker.record(
            UsageRecord(
                agent="test-agent",
                model="openai:gpt-4o",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                request_count=1,
                cost_usd=0.0025,
                latency_ms=350.0,
            )
        )

        resp = await client.get("/api/monitoring/usage")
        assert resp.status_code == 200
        body = resp.json()

        assert body["total_input_tokens"] == 100
        assert body["total_output_tokens"] == 50
        assert body["total_tokens"] == 150
        assert body["total_requests"] == 1
        assert body["total_cost_usd"] == pytest.approx(0.0025)
        assert body["total_latency_ms"] == pytest.approx(350.0)
        assert body["record_count"] == 1

        # Check by_agent breakdown
        assert "test-agent" in body["by_agent"]
        agent_data = body["by_agent"]["test-agent"]
        assert agent_data["input_tokens"] == 100
        assert agent_data["output_tokens"] == 50
        assert agent_data["total_tokens"] == 150
        assert agent_data["cost_usd"] == pytest.approx(0.0025)
        assert agent_data["requests"] == 1

        # Check by_model breakdown
        assert "openai:gpt-4o" in body["by_model"]
        model_data = body["by_model"]["openai:gpt-4o"]
        assert model_data["input_tokens"] == 100
        assert model_data["total_tokens"] == 150

    async def test_usage_aggregates_multiple_records(self, client: httpx.AsyncClient):
        from fireflyframework_genai.observability.usage import (
            UsageRecord,
            default_usage_tracker,
        )

        default_usage_tracker.record(
            UsageRecord(
                agent="agent-a",
                model="openai:gpt-4o",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                request_count=1,
                cost_usd=0.002,
                latency_ms=200.0,
            )
        )
        default_usage_tracker.record(
            UsageRecord(
                agent="agent-b",
                model="anthropic:claude-3",
                input_tokens=200,
                output_tokens=100,
                total_tokens=300,
                request_count=1,
                cost_usd=0.005,
                latency_ms=450.0,
            )
        )

        resp = await client.get("/api/monitoring/usage")
        assert resp.status_code == 200
        body = resp.json()

        assert body["total_input_tokens"] == 300
        assert body["total_output_tokens"] == 150
        assert body["total_tokens"] == 450
        assert body["total_requests"] == 2
        assert body["total_cost_usd"] == pytest.approx(0.007)
        assert body["record_count"] == 2

        # Both agents and models should appear
        assert "agent-a" in body["by_agent"]
        assert "agent-b" in body["by_agent"]
        assert "openai:gpt-4o" in body["by_model"]
        assert "anthropic:claude-3" in body["by_model"]
