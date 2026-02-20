"""Tests for studio configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fireflyframework_genai.studio.config import StudioConfig


@pytest.fixture(autouse=True)
def _clean_studio_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear any ambient FIREFLY_STUDIO_* env vars to isolate tests."""
    for key in list(os.environ):
        if key.startswith("FIREFLY_STUDIO_"):
            monkeypatch.delenv(key, raising=False)


class TestStudioConfigDefaults:
    def test_default_host(self) -> None:
        cfg = StudioConfig(_env_file=None)
        assert cfg.host == "127.0.0.1"

    def test_default_port(self) -> None:
        cfg = StudioConfig(_env_file=None)
        assert cfg.port == 8470

    def test_default_open_browser(self) -> None:
        cfg = StudioConfig(_env_file=None)
        assert cfg.open_browser is True

    def test_default_dev_mode(self) -> None:
        cfg = StudioConfig(_env_file=None)
        assert cfg.dev_mode is False

    def test_default_projects_dir(self) -> None:
        cfg = StudioConfig(_env_file=None)
        assert cfg.projects_dir == Path.home() / ".firefly-studio" / "projects"

    def test_default_log_level(self) -> None:
        cfg = StudioConfig(_env_file=None)
        assert cfg.log_level == "info"


class TestStudioConfigEnvOverrides:
    def test_host_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_STUDIO_HOST", "0.0.0.0")
        cfg = StudioConfig(_env_file=None)
        assert cfg.host == "0.0.0.0"

    def test_port_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_STUDIO_PORT", "9090")
        cfg = StudioConfig(_env_file=None)
        assert cfg.port == 9090

    def test_open_browser_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_STUDIO_OPEN_BROWSER", "false")
        cfg = StudioConfig(_env_file=None)
        assert cfg.open_browser is False

    def test_dev_mode_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_STUDIO_DEV_MODE", "true")
        cfg = StudioConfig(_env_file=None)
        assert cfg.dev_mode is True

    def test_log_level_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_STUDIO_LOG_LEVEL", "debug")
        cfg = StudioConfig(_env_file=None)
        assert cfg.log_level == "debug"

    def test_projects_dir_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_STUDIO_PROJECTS_DIR", "/tmp/my-projects")
        cfg = StudioConfig(_env_file=None)
        assert cfg.projects_dir == Path("/tmp/my-projects")
