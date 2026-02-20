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

"""Studio settings persistence — API keys, model defaults, and setup state.

Settings are stored at ``~/.firefly-studio/settings.json`` with ``0600``
permissions.  On startup, saved API keys are injected into ``os.environ``
so that PydanticAI providers pick them up via their standard env vars.
Existing environment variables always take precedence.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path.home() / ".firefly-studio" / "settings.json"

# Mapping from credential field names to the env var PydanticAI expects.
_CREDENTIAL_ENV_MAP: dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "google_api_key": "GOOGLE_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "mistral_api_key": "MISTRAL_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "cohere_api_key": "CO_API_KEY",
    "azure_openai_api_key": "AZURE_OPENAI_API_KEY",
    "azure_openai_endpoint": "AZURE_OPENAI_ENDPOINT",
    "aws_access_key_id": "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "aws_default_region": "AWS_DEFAULT_REGION",
    "ollama_base_url": "OLLAMA_BASE_URL",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ProviderCredentials(BaseModel):
    """API keys and endpoints for all supported LLM providers."""

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_endpoint: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_default_region: SecretStr | None = None
    ollama_base_url: SecretStr | None = None


class ModelDefaults(BaseModel):
    """Default model configuration for Studio sessions."""

    default_model: str = "openai:gpt-4o"
    temperature: float = 0.7
    retries: int = 3


class StudioSettings(BaseModel):
    """Top-level settings persisted to disk."""

    credentials: ProviderCredentials = ProviderCredentials()
    model_defaults: ModelDefaults = ModelDefaults()
    setup_complete: bool = False


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def is_first_start(path: Path | None = None) -> bool:
    """Return ``True`` when no settings file exists on disk."""
    return not (path or DEFAULT_SETTINGS_PATH).exists()


def load_settings(path: Path | None = None) -> StudioSettings:
    """Load settings from *path*, returning defaults if missing or corrupt."""
    settings_path = path or DEFAULT_SETTINGS_PATH
    if not settings_path.exists():
        return StudioSettings()
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
        return StudioSettings.model_validate(raw)
    except Exception:
        logger.warning("Corrupt settings file at %s — using defaults", settings_path)
        return StudioSettings()


def save_settings(settings: StudioSettings, path: Path | None = None) -> None:
    """Persist *settings* to disk with ``0600`` permissions."""
    settings_path = path or DEFAULT_SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Serialize SecretStr fields as plain strings for JSON storage.
    data = _settings_to_dict(settings)
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Enforce owner-only read/write.
    settings_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def apply_settings_to_env(settings: StudioSettings) -> None:
    """Inject saved credentials into ``os.environ`` (existing vars take precedence)."""
    for field_name, env_var in _CREDENTIAL_ENV_MAP.items():
        value: SecretStr | None = getattr(settings.credentials, field_name, None)
        if value is not None and env_var not in os.environ:
            os.environ[env_var] = value.get_secret_value()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_to_dict(settings: StudioSettings) -> dict[str, Any]:
    """Convert settings to a JSON-serializable dict, unwrapping ``SecretStr``."""
    creds: dict[str, str | None] = {}
    for field_name in ProviderCredentials.model_fields:
        val: SecretStr | None = getattr(settings.credentials, field_name)
        creds[field_name] = val.get_secret_value() if val is not None else None

    return {
        "credentials": creds,
        "model_defaults": settings.model_defaults.model_dump(),
        "setup_complete": settings.setup_complete,
    }
