"""Tests for observability/events.py."""

from __future__ import annotations

from fireflyframework_agentic.observability.events import FireflyEvent, FireflyEvents


class TestFireflyEvent:
    def test_event_fields(self) -> None:
        event = FireflyEvent(event_type="test.event", agent="my-agent")
        assert event.event_type == "test.event"
        assert event.agent == "my-agent"
        assert event.timestamp is not None


class TestFireflyEvents:
    def test_agent_started(self) -> None:
        events = FireflyEvents()
        events.agent_started("my-agent", model="gpt-4o")

    def test_agent_completed(self) -> None:
        events = FireflyEvents()
        events.agent_completed("my-agent", tokens=100, latency_ms=50.0)

    def test_agent_error(self) -> None:
        events = FireflyEvents()
        events.agent_error("my-agent", error="timeout")

    def test_tool_executed(self) -> None:
        events = FireflyEvents()
        events.tool_executed("my-tool", success=True, latency_ms=10.0)

    def test_reasoning_step(self) -> None:
        events = FireflyEvents()
        events.reasoning_step("cot", step=1, step_type="think")
