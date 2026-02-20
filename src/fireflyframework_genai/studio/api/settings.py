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

"""Settings REST API endpoints for Firefly Studio.

Provides ``GET/POST /api/settings`` for managing provider credentials
and model defaults, plus ``GET /api/settings/status`` for first-start
detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

from fireflyframework_genai.studio.settings import (
    DEFAULT_SETTINGS_PATH,
    ModelDefaults,
    ProviderCredentials,
    StudioSettings,
    apply_settings_to_env,
    is_first_start,
    load_settings,
    save_settings,
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CredentialsPayload(BaseModel):
    """Inbound credential fields — all optional plain strings."""

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    groq_api_key: str | None = None
    mistral_api_key: str | None = None
    deepseek_api_key: str | None = None
    cohere_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_default_region: str | None = None
    ollama_base_url: str | None = None


class ModelDefaultsPayload(BaseModel):
    """Inbound model-default fields — all optional for partial update."""

    default_model: str | None = None
    temperature: float | None = None
    retries: int | None = None


class SaveSettingsRequest(BaseModel):
    """Body for ``POST /api/settings``."""

    credentials: CredentialsPayload | None = None
    model_defaults: ModelDefaultsPayload | None = None
    setup_complete: bool | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_key(value: str) -> str:
    """Return a masked version of an API key, showing only the last 4 chars."""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def _settings_to_response(settings: StudioSettings) -> dict[str, Any]:
    """Serialise settings for a GET response, masking secret values."""
    creds: dict[str, str | None] = {}
    for field_name in ProviderCredentials.model_fields:
        val = getattr(settings.credentials, field_name)
        if val is not None:
            creds[field_name] = _mask_key(val.get_secret_value())
        else:
            creds[field_name] = None

    return {
        "credentials": creds,
        "model_defaults": settings.model_defaults.model_dump(),
        "setup_complete": settings.setup_complete,
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_settings_router(settings_path: Path | None = None) -> APIRouter:
    """Create an :class:`APIRouter` for Studio settings management.

    Endpoints
    ---------
    ``GET  /api/settings``        — current settings (keys masked).
    ``POST /api/settings``        — save / merge settings.
    ``GET  /api/settings/status`` — lightweight first-start check.
    """
    router = APIRouter(prefix="/api/settings", tags=["settings"])
    path = settings_path or DEFAULT_SETTINGS_PATH

    @router.get("")
    async def get_settings() -> dict[str, Any]:
        settings = load_settings(path)
        return _settings_to_response(settings)

    @router.post("")
    async def post_settings(body: SaveSettingsRequest) -> dict[str, Any]:
        settings = load_settings(path)

        # --- Merge credentials (null = keep existing) ---
        if body.credentials is not None:
            from pydantic import SecretStr

            merged: dict[str, Any] = {}
            for field_name in ProviderCredentials.model_fields:
                incoming = getattr(body.credentials, field_name)
                if incoming is not None:
                    merged[field_name] = SecretStr(incoming)
                else:
                    merged[field_name] = getattr(settings.credentials, field_name)
            settings.credentials = ProviderCredentials(**merged)

        # --- Merge model defaults ---
        if body.model_defaults is not None:
            current = settings.model_defaults.model_dump()
            for field_name in ModelDefaults.model_fields:
                incoming = getattr(body.model_defaults, field_name)
                if incoming is not None:
                    current[field_name] = incoming
            settings.model_defaults = ModelDefaults(**current)

        # --- setup_complete flag ---
        if body.setup_complete is not None:
            settings.setup_complete = body.setup_complete

        save_settings(settings, path)
        apply_settings_to_env(settings)

        return _settings_to_response(settings)

    @router.get("/status")
    async def settings_status() -> dict[str, Any]:
        first_start = is_first_start(path)
        if first_start:
            return {"first_start": True, "setup_complete": False}
        settings = load_settings(path)
        return {"first_start": False, "setup_complete": settings.setup_complete}

    return router
