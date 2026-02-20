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

"""Configuration for Firefly Studio.

All configuration values can be overridden via environment variables prefixed
with ``FIREFLY_STUDIO_``.  For example, setting ``FIREFLY_STUDIO_PORT``
in the environment will override the ``port`` field.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class StudioConfig(BaseSettings):
    """Studio configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="FIREFLY_STUDIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    """Address the Studio server binds to."""

    port: int = 8470
    """Port the Studio server listens on."""

    open_browser: bool = True
    """Whether to open the browser automatically on launch."""

    dev_mode: bool = False
    """Enable development mode (e.g. hot reload, verbose logging)."""

    projects_dir: Path = Path.home() / ".firefly-studio" / "projects"
    """Directory where Studio persists project data."""

    log_level: str = "info"
    """Logging level for Studio."""
