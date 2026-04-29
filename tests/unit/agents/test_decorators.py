"""Tests for agents/decorators.py."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.decorators import firefly_agent
from fireflyframework_agentic.agents.registry import agent_registry


class TestFireflyAgentDecorator:
    def test_creates_agent(self) -> None:
        @firefly_agent("test-deco", model=TestModel(), auto_register=False)
        def instruct(ctx: object) -> str:
            return "be helpful"

        assert isinstance(instruct, FireflyAgent)
        assert instruct.name == "test-deco"

    def test_uses_docstring_as_description(self) -> None:
        @firefly_agent("test-doc", model=TestModel(), auto_register=False)
        def instruct(ctx: object) -> str:
            """My description."""
            return "ok"

        assert instruct.description == "My description."

    def test_auto_register(self) -> None:
        try:

            @firefly_agent("test-autoreg", model=TestModel(), auto_register=True)
            def instruct(ctx: object) -> str:
                return "ok"

            assert agent_registry.has("test-autoreg")
        finally:
            if agent_registry.has("test-autoreg"):
                agent_registry.unregister("test-autoreg")

    def test_tags_and_version(self) -> None:
        @firefly_agent("test-tv", model=TestModel(), tags=["a", "b"], version="1.0.0", auto_register=False)
        def instruct(ctx: object) -> str:
            return "ok"

        assert instruct.tags == ["a", "b"]
        assert instruct.version == "1.0.0"
