"""Tests for config.py cross-field validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fireflyframework_genai.config import FireflyGenAIConfig


class TestConfigValidation:
    def test_valid_config(self) -> None:
        cfg = FireflyGenAIConfig(
            budget_limit_usd=10.0,
            budget_alert_threshold_usd=5.0,
        )
        assert cfg.budget_limit_usd == 10.0

    def test_alert_exceeds_limit_raises(self) -> None:
        with pytest.raises(ValidationError, match="budget_alert_threshold_usd"):
            FireflyGenAIConfig(
                budget_limit_usd=5.0,
                budget_alert_threshold_usd=10.0,
            )

    def test_chunk_overlap_exceeds_size_raises(self) -> None:
        with pytest.raises(ValidationError, match="default_chunk_overlap"):
            FireflyGenAIConfig(
                default_chunk_size=100,
                default_chunk_overlap=200,
            )

    def test_qos_consistency_runs_minimum(self) -> None:
        with pytest.raises(ValidationError, match="qos_consistency_runs"):
            FireflyGenAIConfig(qos_consistency_runs=1)

    def test_default_config_is_valid(self) -> None:
        cfg = FireflyGenAIConfig()
        assert cfg.qos_consistency_runs >= 2


class TestConfigAuthAndUsageFields:
    def test_auth_api_keys_default(self) -> None:
        cfg = FireflyGenAIConfig()
        assert cfg.auth_api_keys is None

    def test_auth_bearer_tokens_default(self) -> None:
        cfg = FireflyGenAIConfig()
        assert cfg.auth_bearer_tokens is None

    def test_usage_tracker_max_records_default(self) -> None:
        cfg = FireflyGenAIConfig()
        assert cfg.usage_tracker_max_records == 10_000

    def test_custom_values(self) -> None:
        cfg = FireflyGenAIConfig(
            auth_api_keys=["key1"],
            auth_bearer_tokens=["tok1"],
            usage_tracker_max_records=500,
        )
        assert cfg.auth_api_keys == ["key1"]
        assert cfg.auth_bearer_tokens == ["tok1"]
        assert cfg.usage_tracker_max_records == 500


class TestEmbeddingConfig:
    def test_embedding_defaults(self) -> None:
        cfg = FireflyGenAIConfig()
        assert cfg.default_embedding_model == "openai:text-embedding-3-small"
        assert cfg.embedding_batch_size == 100
        assert cfg.embedding_max_retries == 3

    def test_vector_store_defaults(self) -> None:
        cfg = FireflyGenAIConfig()
        assert cfg.default_vector_store == "memory"
        assert cfg.vector_store_namespace == "default"
