"""Tests for config.py cross-field validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fireflyframework_agentic.config import FireflyAgenticConfig


class TestConfigValidation:
    def test_valid_config(self) -> None:
        cfg = FireflyAgenticConfig(budget_limit_usd=10.0)
        assert cfg.budget_limit_usd == 10.0

    def test_chunk_overlap_exceeds_size_raises(self) -> None:
        with pytest.raises(ValidationError, match="default_chunk_overlap"):
            FireflyAgenticConfig(
                default_chunk_size=100,
                default_chunk_overlap=200,
            )

    def test_qos_consistency_runs_minimum(self) -> None:
        with pytest.raises(ValidationError, match="qos_consistency_runs"):
            FireflyAgenticConfig(qos_consistency_runs=1)

    def test_default_config_is_valid(self) -> None:
        cfg = FireflyAgenticConfig()
        assert cfg.qos_consistency_runs >= 2

    def test_removed_cost_calculator_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="Removed config fields"):
            FireflyAgenticConfig(cost_calculator="auto")

    def test_removed_budget_alert_threshold_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="Removed config fields"):
            FireflyAgenticConfig(budget_alert_threshold_usd=5.0)

    def test_removed_auth_api_keys_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="Removed config fields"):
            FireflyAgenticConfig(auth_api_keys=["key1"])

    def test_removed_auth_bearer_tokens_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="Removed config fields"):
            FireflyAgenticConfig(auth_bearer_tokens=["tok1"])

    def test_removed_cors_allowed_origins_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="Removed config fields"):
            FireflyAgenticConfig(cors_allowed_origins=["https://app.example.com"])


class TestConfigUsageFields:
    def test_usage_tracker_max_records_default(self) -> None:
        cfg = FireflyAgenticConfig()
        assert cfg.usage_tracker_max_records == 10_000

    def test_custom_values(self) -> None:
        cfg = FireflyAgenticConfig(
            usage_tracker_max_records=500,
        )
        assert cfg.usage_tracker_max_records == 500


class TestEmbeddingConfig:
    def test_embedding_defaults(self) -> None:
        cfg = FireflyAgenticConfig()
        assert cfg.default_embedding_model == "openai:text-embedding-3-small"
        assert cfg.embedding_batch_size == 100
        assert cfg.embedding_max_retries == 3

    def test_vector_store_defaults(self) -> None:
        cfg = FireflyAgenticConfig()
        assert cfg.default_vector_store == "memory"
        assert cfg.vector_store_namespace == "default"
