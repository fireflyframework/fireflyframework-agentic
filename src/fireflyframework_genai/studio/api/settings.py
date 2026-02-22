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

"""Settings REST API endpoints for Firefly Agentic Studio.

Provides ``GET/POST /api/settings`` for managing provider credentials
and model defaults, plus ``GET /api/settings/status`` for first-start
detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

from fireflyframework_genai.studio.settings import (
    DEFAULT_SETTINGS_PATH,
    ModelDefaults,
    ProviderCredentials,
    ServiceCredential,
    StudioSettings,
    ToolCredentials,
    UserProfile,
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


class UserProfilePayload(BaseModel):
    """Inbound user profile fields — all optional for partial update."""

    name: str | None = None
    role: str | None = None
    context: str | None = None
    assistant_name: str | None = None


class ToolCredentialsPayload(BaseModel):
    """Inbound tool credential fields — all optional for partial update."""

    serpapi_api_key: str | None = None
    serper_api_key: str | None = None
    tavily_api_key: str | None = None
    database_url: str | None = None
    redis_url: str | None = None
    slack_bot_token: str | None = None
    telegram_bot_token: str | None = None


class SaveSettingsRequest(BaseModel):
    """Body for ``POST /api/settings``."""

    credentials: CredentialsPayload | None = None
    model_defaults: ModelDefaultsPayload | None = None
    user_profile: UserProfilePayload | None = None
    tool_credentials: ToolCredentialsPayload | None = None
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

    tool_creds: dict[str, str | None] = {}
    for field_name in ToolCredentials.model_fields:
        val = getattr(settings.tool_credentials, field_name)
        if val is not None:
            tool_creds[field_name] = _mask_key(val.get_secret_value())
        else:
            tool_creds[field_name] = None

    return {
        "credentials": creds,
        "model_defaults": settings.model_defaults.model_dump(),
        "user_profile": settings.user_profile.model_dump(),
        "tool_credentials": tool_creds,
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

        # --- Merge user profile ---
        if body.user_profile is not None:
            current_profile = settings.user_profile.model_dump()
            for field_name in UserProfile.model_fields:
                incoming = getattr(body.user_profile, field_name)
                if incoming is not None:
                    current_profile[field_name] = incoming
            settings.user_profile = UserProfile(**current_profile)

        # --- Merge tool credentials ---
        if body.tool_credentials is not None:
            from pydantic import SecretStr as _SecretStr

            tool_merged: dict[str, Any] = {}
            for field_name in ToolCredentials.model_fields:
                incoming = getattr(body.tool_credentials, field_name)
                if incoming is not None:
                    tool_merged[field_name] = _SecretStr(incoming)
                else:
                    tool_merged[field_name] = getattr(settings.tool_credentials, field_name)
            settings.tool_credentials = ToolCredentials(**tool_merged)

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

    # -----------------------------------------------------------------------
    # Service credentials CRUD
    # -----------------------------------------------------------------------

    @router.get("/services")
    async def list_services() -> list[dict]:
        """List all service credentials (with secrets masked)."""
        settings = load_settings(path)
        result = []
        for sc in settings.service_credentials:
            entry = sc.model_dump()
            # Mask secret fields
            for field in ("password", "connection_url", "api_key", "token"):
                val = getattr(sc, field, None)
                if val is not None:
                    secret_val = val.get_secret_value() if hasattr(val, "get_secret_value") else str(val)
                    entry[field] = "***" if secret_val else ""
                else:
                    entry[field] = None
            result.append(entry)
        return result

    @router.post("/services")
    async def add_service(req: dict) -> dict:
        """Add or update a service credential."""
        settings = load_settings(path)

        # Preserve existing secret values when the incoming value is the
        # mask placeholder ("***") sent by list_services.
        _mask = "***"
        _secret_fields = ("password", "connection_url", "api_key", "token")
        incoming_id = req.get("id")
        if incoming_id:
            old_sc = next(
                (s for s in settings.service_credentials if s.id == incoming_id),
                None,
            )
            if old_sc is not None:
                for field in _secret_fields:
                    if req.get(field) == _mask:
                        existing_val = getattr(old_sc, field, None)
                        if existing_val is not None:
                            req[field] = (
                                existing_val.get_secret_value()
                                if hasattr(existing_val, "get_secret_value")
                                else str(existing_val)
                            )
                        else:
                            req.pop(field, None)

        sc = ServiceCredential(**req)
        existing = [s for s in settings.service_credentials if s.id != sc.id]
        existing.append(sc)
        settings.service_credentials = existing
        save_settings(settings, path)
        return {"status": "saved", "id": sc.id}

    @router.delete("/services/{service_id}")
    async def delete_service(service_id: str) -> dict:
        """Delete a service credential by ID."""
        settings = load_settings(path)
        before = len(settings.service_credentials)
        settings.service_credentials = [s for s in settings.service_credentials if s.id != service_id]
        if len(settings.service_credentials) == before:
            raise HTTPException(status_code=404, detail=f"Service '{service_id}' not found")
        save_settings(settings, path)
        return {"status": "deleted", "id": service_id}

    @router.post("/services/{service_id}/test")
    async def test_service(service_id: str) -> dict:
        """Test connectivity for a service credential."""
        settings = load_settings(path)
        sc = next((s for s in settings.service_credentials if s.id == service_id), None)
        if not sc:
            raise HTTPException(status_code=404, detail=f"Service '{service_id}' not found")

        # Basic connectivity test based on service type
        try:
            if sc.service_type in ("serpapi", "serper", "tavily"):
                # API key services - just verify key is set
                if sc.api_key and sc.api_key.get_secret_value():
                    return {
                        "status": "ok",
                        "message": f"API key configured for {sc.service_type}",
                    }
                return {"status": "error", "message": "No API key set"}

            if sc.service_type in ("slack", "telegram", "discord"):
                # Token services
                if sc.token and sc.token.get_secret_value():
                    return {
                        "status": "ok",
                        "message": f"Token configured for {sc.service_type}",
                    }
                return {"status": "error", "message": "No token set"}

            # Database/queue services - check host is set
            if sc.host or (sc.connection_url and sc.connection_url.get_secret_value()):
                return {
                    "status": "ok",
                    "message": (f"Connection details configured for {sc.service_type}"),
                }
            return {
                "status": "error",
                "message": "No host or connection URL configured",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return router
