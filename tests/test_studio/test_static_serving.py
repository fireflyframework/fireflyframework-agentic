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

"""Tests for static file serving of the bundled Studio frontend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed")

import httpx

from fireflyframework_genai.studio.server import create_studio_app


@pytest.fixture()
def static_dir(tmp_path: Path) -> Path:
    """Create a temporary static directory with a minimal SPA."""
    d = tmp_path / "static"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><html><body>Firefly Studio</body></html>")
    app_dir = d / "_app"
    app_dir.mkdir()
    (app_dir / "app.js").write_text("console.log('ok');")
    return d


class TestStaticServing:
    async def test_serves_index_html_when_static_dir_exists(self, static_dir: Path):
        """When bundled static files exist, / serves index.html."""
        with patch(
            "fireflyframework_genai.studio.server._get_default_static_dir",
            return_value=static_dir,
        ):
            app = create_studio_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "Firefly Studio" in resp.text

    async def test_api_routes_work_with_static_serving(self, static_dir: Path):
        """API routes still work when static files are mounted."""
        with patch(
            "fireflyframework_genai.studio.server._get_default_static_dir",
            return_value=static_dir,
        ):
            app = create_studio_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    async def test_no_static_serving_without_index_html(self):
        """When no bundled frontend exists, the app still starts normally."""
        app = create_studio_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # API should still work
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
