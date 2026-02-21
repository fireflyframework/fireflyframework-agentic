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

"""Tests for Cloudflare Tunnel management."""

from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from fireflyframework_genai.studio.tunnel import TunnelManager


class TestTunnelManager:
    def test_cloudflared_not_installed(self):
        with patch.object(shutil, "which", return_value=None):
            tm = TunnelManager(port=8470)
            assert tm.is_available() is False

    def test_cloudflared_installed(self):
        with patch.object(shutil, "which", return_value="/usr/local/bin/cloudflared"):
            tm = TunnelManager(port=8470)
            assert tm.is_available() is True

    def test_initial_status_is_stopped(self):
        tm = TunnelManager(port=8470)
        status = tm.get_status()
        assert status["active"] is False
        assert status["url"] is None
        assert status["port"] == 8470

    def test_custom_port(self):
        tm = TunnelManager(port=9090)
        assert tm.port == 9090
        assert tm.get_status()["port"] == 9090

    async def test_start_raises_when_cloudflared_not_available(self):
        with patch.object(shutil, "which", return_value=None):
            tm = TunnelManager(port=8470)
            with pytest.raises(RuntimeError, match="cloudflared is not installed"):
                await tm.start()

    async def test_start_raises_when_already_running(self):
        tm = TunnelManager(port=8470)
        tm._process = object()  # fake a running process
        with pytest.raises(RuntimeError, match="already running"):
            await tm.start()

    async def test_stop_when_not_running(self):
        tm = TunnelManager(port=8470)
        await tm.stop()  # Should not raise
        assert tm.get_status()["active"] is False
