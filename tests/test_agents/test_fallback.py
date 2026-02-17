"""Tests for agents/fallback.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fireflyframework_genai.agents.fallback import FallbackModelWrapper


class TestFallbackModelWrapper:
    def test_primary_is_first_model(self) -> None:
        fw = FallbackModelWrapper(models=["a", "b", "c"])
        assert fw.primary == "a"
        assert fw.current == "a"

    def test_next_model_advances(self) -> None:
        fw = FallbackModelWrapper(models=["a", "b", "c"])
        assert fw.next_model() == "b"
        assert fw.current == "b"
        assert fw.next_model() == "c"
        assert fw.current == "c"
        assert fw.next_model() is None

    def test_reset(self) -> None:
        fw = FallbackModelWrapper(models=["a", "b"])
        fw.next_model()
        fw.reset()
        assert fw.current == "a"

    def test_max_fallback_attempts(self) -> None:
        fw = FallbackModelWrapper(models=["a", "b", "c"], max_fallback_attempts=2)
        assert fw.next_model() == "b"
        assert fw.next_model() is None

    def test_empty_models_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one model"):
            FallbackModelWrapper(models=[])

    def test_models_property_returns_copy(self) -> None:
        fw = FallbackModelWrapper(models=["a", "b"])
        models = fw.models
        models.append("c")
        assert len(fw.models) == 2

    def test_accepts_model_objects(self) -> None:
        """FallbackModelWrapper should accept Model objects alongside strings."""
        mock_model = MagicMock()
        mock_model.model_name = "gpt-4o"
        fw = FallbackModelWrapper(models=["openai:gpt-4o-mini", mock_model])
        assert fw.primary == "openai:gpt-4o-mini"
        next_m = fw.next_model()
        assert next_m is mock_model

    def test_mixed_string_and_model_objects(self) -> None:
        """Fallback chain with mixed strings and Model objects."""
        mock_model = MagicMock()
        mock_model.model_name = "claude-3-5-sonnet"
        fw = FallbackModelWrapper(models=["openai:gpt-4o", mock_model, "anthropic:claude-3-5-haiku-latest"])
        assert fw.next_model() is mock_model
        assert fw.next_model() == "anthropic:claude-3-5-haiku-latest"
        assert fw.next_model() is None
