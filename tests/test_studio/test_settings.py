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

"""Tests for Studio settings persistence and REST API."""

from __future__ import annotations

import json
import os
import stat

import pytest
from pydantic import SecretStr

from fireflyframework_genai.studio.settings import (
    ModelDefaults,
    ProviderCredentials,
    StudioSettings,
    apply_settings_to_env,
    is_first_start,
    load_settings,
    save_settings,
)

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.server import create_studio_app

# ---------------------------------------------------------------------------
# Unit tests — file I/O
# ---------------------------------------------------------------------------


class TestIsFirstStart:
    def test_true_when_no_file(self, tmp_path):
        assert is_first_start(tmp_path / "settings.json") is True

    def test_false_when_file_exists(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        assert is_first_start(settings_file) is False


class TestLoadSettings:
    def test_returns_defaults_when_no_file(self, tmp_path):
        settings = load_settings(tmp_path / "settings.json")
        assert settings.setup_complete is False
        assert settings.model_defaults.default_model == "openai:gpt-4o"

    def test_handles_corrupt_file(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not json!!!")
        settings = load_settings(settings_file)
        assert settings.setup_complete is False

    def test_loads_persisted_data(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        data = {
            "credentials": {"openai_api_key": "sk-test123"},
            "model_defaults": {"default_model": "anthropic:claude-3-opus", "temperature": 0.5, "retries": 2},
            "setup_complete": True,
        }
        settings_file.write_text(json.dumps(data))
        settings = load_settings(settings_file)
        assert settings.setup_complete is True
        assert settings.model_defaults.default_model == "anthropic:claude-3-opus"
        assert settings.model_defaults.temperature == 0.5
        assert settings.credentials.openai_api_key is not None
        assert settings.credentials.openai_api_key.get_secret_value() == "sk-test123"


class TestSaveSettings:
    def test_creates_file(self, tmp_path):
        settings_file = tmp_path / "sub" / "settings.json"
        settings = StudioSettings()
        save_settings(settings, settings_file)
        assert settings_file.exists()

    def test_enforces_permissions(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        save_settings(StudioSettings(), settings_file)
        mode = settings_file.stat().st_mode
        assert mode & stat.S_IRUSR  # owner read
        assert mode & stat.S_IWUSR  # owner write
        assert not mode & stat.S_IRGRP  # no group read
        assert not mode & stat.S_IROTH  # no other read

    def test_roundtrip(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        original = StudioSettings(
            credentials=ProviderCredentials(openai_api_key=SecretStr("sk-roundtrip")),
            model_defaults=ModelDefaults(default_model="test:model", temperature=1.0, retries=5),
            setup_complete=True,
        )
        save_settings(original, settings_file)
        loaded = load_settings(settings_file)
        assert loaded.setup_complete is True
        assert loaded.model_defaults.default_model == "test:model"
        assert loaded.model_defaults.temperature == 1.0
        assert loaded.model_defaults.retries == 5
        assert loaded.credentials.openai_api_key is not None
        assert loaded.credentials.openai_api_key.get_secret_value() == "sk-roundtrip"


class TestApplySettingsToEnv:
    def test_applies_keys(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        settings = StudioSettings(
            credentials=ProviderCredentials(openai_api_key=SecretStr("sk-env-test")),
        )
        apply_settings_to_env(settings)
        assert os.environ.get("OPENAI_API_KEY") == "sk-env-test"
        # Cleanup
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_does_not_override_existing(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-existing")
        settings = StudioSettings(
            credentials=ProviderCredentials(openai_api_key=SecretStr("sk-new")),
        )
        apply_settings_to_env(settings)
        assert os.environ["OPENAI_API_KEY"] == "sk-existing"


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path):
    """Create a Studio app with an isolated settings path."""
    settings_file = tmp_path / "settings.json"
    return create_studio_app(settings_path=settings_file)


@pytest.fixture()
async def client(app):
    """Provide an async httpx client bound to the test app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSettingsAPI:
    async def test_get_settings_returns_200(self, client: httpx.AsyncClient):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200

    async def test_get_settings_structure(self, client: httpx.AsyncClient):
        resp = await client.get("/api/settings")
        body = resp.json()
        assert "credentials" in body
        assert "model_defaults" in body
        assert "setup_complete" in body

    async def test_post_settings_persists(self, client: httpx.AsyncClient):
        payload = {
            "credentials": {"openai_api_key": "sk-test-persist"},
            "model_defaults": {"default_model": "openai:gpt-4o-mini"},
            "setup_complete": True,
        }
        resp = await client.post("/api/settings", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["setup_complete"] is True
        assert body["model_defaults"]["default_model"] == "openai:gpt-4o-mini"

    async def test_keys_masked_in_get(self, client: httpx.AsyncClient):
        # First save a key
        await client.post("/api/settings", json={"credentials": {"openai_api_key": "sk-maskedtest1234"}})
        # Then GET and verify masking
        resp = await client.get("/api/settings")
        body = resp.json()
        masked = body["credentials"]["openai_api_key"]
        assert masked.startswith("****")
        assert masked.endswith("1234")
        assert "maskedtest" not in masked

    async def test_status_first_start(self, client: httpx.AsyncClient):
        resp = await client.get("/api/settings/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["first_start"] is True
        assert body["setup_complete"] is False

    async def test_status_after_setup(self, client: httpx.AsyncClient):
        await client.post("/api/settings", json={"setup_complete": True})
        resp = await client.get("/api/settings/status")
        body = resp.json()
        assert body["first_start"] is False
        assert body["setup_complete"] is True

    async def test_merge_preserves_existing(self, client: httpx.AsyncClient):
        # Save openai key
        await client.post("/api/settings", json={"credentials": {"openai_api_key": "sk-first"}})
        # Save anthropic key (openai should be preserved)
        await client.post("/api/settings", json={"credentials": {"anthropic_api_key": "sk-ant-second"}})
        # Verify both exist
        resp = await client.get("/api/settings")
        body = resp.json()
        assert body["credentials"]["openai_api_key"] is not None
        assert body["credentials"]["anthropic_api_key"] is not None
