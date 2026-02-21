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

"""Central configuration for the Firefly GenAI framework.

All configuration values can be overridden via environment variables prefixed
with ``FIREFLY_GENAI_``.  For example, setting ``FIREFLY_GENAI_DEFAULT_MODEL``
in the environment will override the ``default_model`` field.
"""

from __future__ import annotations

import threading
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FireflyGenAIConfig(BaseSettings):
    """Framework-wide configuration loaded from environment variables.

    This configuration object centralises every tunable knob in the framework.
    Individual modules read from this configuration at runtime via
    :func:`get_config` so that users only need to set environment variables
    (or pass values programmatically) once.
    """

    model_config = SettingsConfigDict(
        env_prefix="FIREFLY_GENAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Model defaults ------------------------------------------------------
    default_model: str = "openai:gpt-4o"
    """The default Pydantic AI model identifier used when no model is specified."""

    default_temperature: float = 0.7
    """Default sampling temperature for LLM calls."""

    max_retries: int = 3
    """Default maximum number of retries for agent runs and tool calls."""

    # -- Observability -------------------------------------------------------
    observability_enabled: bool = True
    """Whether OpenTelemetry instrumentation is active."""

    otlp_endpoint: str | None = None
    """OTLP exporter endpoint.  When *None*, traces are exported to the console."""

    log_level: str = "INFO"
    """Logging level for the framework's internal logger."""

    # -- Prompts -------------------------------------------------------------
    prompt_templates_dir: str = "prompts/"
    """Default directory from which to load Jinja2 prompt templates."""

    # -- Experiments ---------------------------------------------------------
    experiment_storage: str = "sqlite:///experiments.db"
    """Connection string for experiment result persistence."""

    # -- Plugins -------------------------------------------------------------
    plugin_auto_discover: bool = True
    """Whether to scan ``entry_points`` for third-party plugins on startup."""

    # -- Tools ---------------------------------------------------------------
    tools_sandbox_enabled: bool = True
    """Whether built-in tools that execute external operations run in a sandbox."""

    # -- Content processing --------------------------------------------------
    default_chunk_size: int = 4000
    """Default maximum number of estimated tokens per chunk."""

    default_chunk_overlap: int = 200
    """Default token overlap between consecutive chunks."""

    max_context_tokens: int = 128_000
    """Maximum context window size in tokens."""

    # -- Validation & QoS ---------------------------------------------------
    validation_enabled: bool = True
    """Whether output validation is enabled by default."""

    qos_min_confidence: float = 0.7
    """Minimum confidence threshold for QoS guards."""

    qos_consistency_runs: int = 3
    """Number of runs for consistency checking."""

    # -- Cost tracking & metering --------------------------------------------
    cost_tracking_enabled: bool = True
    """Whether usage and cost tracking is active."""

    budget_limit_usd: float | None = None
    """Hard budget limit in USD.  When exceeded, a warning is logged."""

    budget_alert_threshold_usd: float | None = None
    """Soft alert threshold in USD.  A warning is logged when reached."""

    cost_calculator: Literal["auto", "genai_prices", "static"] = "auto"
    """Cost calculator preference: ``"auto"``, ``"genai_prices"``, or ``"static"``."""

    # -- Memory -------------------------------------------------------------
    memory_backend: str = "in_memory"
    """Default memory backend: ``"in_memory"``, ``"file"``, ``"postgres"``, or ``"mongodb"``."""

    memory_max_conversation_tokens: int = 128_000
    """Maximum tokens retained in conversation memory per conversation."""

    memory_summarize_threshold: int = 10
    """Number of evicted turns before auto-summarization triggers."""

    memory_file_dir: str = ".firefly_memory"
    """Directory for file-based memory persistence."""

    # PostgreSQL backend configuration
    memory_postgres_url: str | None = None
    """PostgreSQL connection URL (e.g., ``postgresql://user:pass@localhost/db``)."""

    memory_postgres_pool_size: int = 10
    """Maximum connections in PostgreSQL pool."""

    memory_postgres_pool_min_size: int = 2
    """Minimum connections in PostgreSQL pool."""

    memory_postgres_schema: str = "firefly_memory"
    """PostgreSQL schema name for table isolation."""

    # MongoDB backend configuration
    memory_mongodb_url: str | None = None
    """MongoDB connection URL (e.g., ``mongodb://localhost:27017/``)."""

    memory_mongodb_database: str = "firefly_memory"
    """MongoDB database name."""

    memory_mongodb_collection: str = "entries"
    """MongoDB collection name for memory entries."""

    memory_mongodb_pool_size: int = 10
    """Maximum connections in MongoDB pool."""

    # -- Authentication -------------------------------------------------------
    auth_api_keys: list[str] | None = None
    """List of valid API keys for REST endpoint authentication.  When set,
    the auth middleware is automatically enabled."""

    auth_bearer_tokens: list[str] | None = None
    """List of valid bearer tokens for REST endpoint authentication."""

    # -- Usage tracker -------------------------------------------------------
    usage_tracker_max_records: int = 10_000
    """Maximum number of usage records retained in memory.  Oldest records
    are evicted when this limit is reached (FIFO)."""

    # -- Quota & Rate Limiting -----------------------------------------------
    quota_enabled: bool = False
    """Whether API quota management and rate limiting is active."""

    quota_budget_daily_usd: float | None = None
    """Daily spending budget in USD.  When exceeded, requests are rejected."""

    quota_rate_limits: dict[str, int] = {}
    """Per-model rate limits as ``{model: requests_per_minute}``.
    Example: ``{"openai:gpt-4o": 60, "openai:gpt-4o-mini": 200}``."""

    quota_adaptive_backoff: bool = True
    """Whether to use adaptive exponential backoff for 429 (rate limit) responses."""

    rate_limit_max_retries: int = 3
    """Max retry attempts for HTTP 429 rate limit errors."""

    rate_limit_base_delay: float = 1.0
    """Base delay (seconds) for rate limit exponential backoff."""

    rate_limit_max_delay: float = 60.0
    """Maximum delay (seconds) between rate limit retries."""

    # -- Security (RBAC & Encryption) ----------------------------------------
    rbac_enabled: bool = False
    """Whether Role-Based Access Control is active."""

    rbac_jwt_secret: str | None = None
    """JWT secret key for token signing and verification."""

    rbac_multi_tenant: bool = False
    """Whether to enforce tenant isolation in RBAC."""

    encryption_enabled: bool = False
    """Whether data encryption at rest is active."""

    encryption_key: str | None = None
    """Encryption key for AES-256-GCM (32 bytes, or password for key derivation)."""

    cors_allowed_origins: list[str] = []
    """List of allowed CORS origins. Empty list = no origins allowed (secure default)."""

    # -- HTTP Connection Pooling ---------------------------------------------
    http_pool_enabled: bool = True
    """Whether to use HTTP connection pooling (requires httpx)."""

    http_pool_size: int = 100
    """Maximum number of HTTP connections in the pool."""

    http_pool_max_keepalive: int = 20
    """Maximum number of idle HTTP connections to keep alive."""

    http_pool_timeout: float = 30.0
    """HTTP request timeout in seconds."""

    @model_validator(mode="after")
    def _validate_cross_fields(self) -> FireflyGenAIConfig:
        """Validate cross-field constraints."""
        if (
            self.budget_alert_threshold_usd is not None
            and self.budget_limit_usd is not None
            and self.budget_alert_threshold_usd > self.budget_limit_usd
        ):
            raise ValueError(
                f"budget_alert_threshold_usd ({self.budget_alert_threshold_usd}) "
                f"must not exceed budget_limit_usd ({self.budget_limit_usd})"
            )
        if self.default_chunk_overlap >= self.default_chunk_size:
            raise ValueError(
                f"default_chunk_overlap ({self.default_chunk_overlap}) "
                f"must be less than default_chunk_size ({self.default_chunk_size})"
            )
        if self.qos_consistency_runs < 2:
            raise ValueError(f"qos_consistency_runs ({self.qos_consistency_runs}) must be >= 2")
        return self


# ---------------------------------------------------------------------------
# Singleton accessor — double-checked locking pattern ensures the config is
# created exactly once, even under concurrent access from multiple threads.
# ---------------------------------------------------------------------------

_config_instance: FireflyGenAIConfig | None = None
_config_lock = threading.Lock()


def get_config() -> FireflyGenAIConfig:
    """Return the singleton :class:`FireflyGenAIConfig` instance.  Thread-safe."""
    global _config_instance  # noqa: PLW0603
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                _config_instance = FireflyGenAIConfig()
    return _config_instance


def reset_config() -> None:
    """Reset the cached configuration.  Useful in tests."""
    global _config_instance  # noqa: PLW0603
    with _config_lock:
        _config_instance = None
