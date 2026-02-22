"""Tests for dynamic model configuration in The Architect and codegen."""

from __future__ import annotations

import json

from fireflyframework_genai.studio.codegen.generator import _get_default_model, generate_python
from fireflyframework_genai.studio.codegen.models import GraphModel, GraphNode, NodeType


class TestDynamicDefaultModel:
    def test_get_default_model_reads_settings(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "model_defaults": {"default_model": "anthropic:claude-sonnet-4-20250514"},
            "setup_complete": True,
        }))
        model = _get_default_model(settings_path=settings_file)
        assert model == "anthropic:claude-sonnet-4-20250514"

    def test_get_default_model_fallback(self, tmp_path):
        model = _get_default_model(settings_path=tmp_path / "nonexistent.json")
        assert model == "openai:gpt-4o"

    def test_codegen_uses_settings_model(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "model_defaults": {"default_model": "google-gla:gemini-2.5-flash"},
        }))

        node = GraphNode(
            id="agent_1", type=NodeType.AGENT, label="Agent",
            position={"x": 0, "y": 0},
            data={"instructions": "Help the user."},  # No model specified
        )
        graph = GraphModel(nodes=[node])
        code = generate_python(graph, settings_path=settings_file)
        assert 'model="google-gla:gemini-2.5-flash"' in code


class TestArchitectDefaultModel:
    def test_architect_instructions_include_default_model(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "model_defaults": {"default_model": "anthropic:claude-sonnet-4-20250514"},
            "user_profile": {"name": "TestUser"},
            "setup_complete": True,
        }))

        from fireflyframework_genai.studio.assistant.agent import _build_instructions
        instructions = _build_instructions(settings_path=settings_file)
        assert "anthropic:claude-sonnet-4-20250514" in instructions
