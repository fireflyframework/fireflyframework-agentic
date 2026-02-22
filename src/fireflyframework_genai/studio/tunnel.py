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

"""Cloudflare Tunnel manager for exposing Studio to the internet.

Uses the ``cloudflared`` binary to create quick tunnels without
requiring a Cloudflare account.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages a cloudflared quick tunnel."""

    def __init__(self, port: int = 8470) -> None:
        self.port = port
        self._process: subprocess.Popen[str] | None = None
        self._url: str | None = None

    def is_available(self) -> bool:
        """Check if cloudflared binary is on PATH."""
        return shutil.which("cloudflared") is not None

    async def start(self) -> str:
        """Start a quick tunnel and return the public URL."""
        if self._process is not None:
            raise RuntimeError("Tunnel already running")

        if not self.is_available():
            raise RuntimeError(
                "cloudflared is not installed. Install it from: "
                "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            )

        self._process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{self.port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        url = await self._wait_for_url(timeout=30)
        self._url = url
        logger.info("Cloudflare Tunnel started: %s", url)
        return url

    async def stop(self) -> None:
        """Terminate the tunnel subprocess."""
        if self._process is not None:
            self._process.terminate()
            self._process.wait(timeout=10)
            self._process = None
            self._url = None
            logger.info("Cloudflare Tunnel stopped")

    def get_status(self) -> dict[str, Any]:
        """Return current tunnel status."""
        return {
            "active": self._process is not None,
            "url": self._url,
            "port": self.port,
        }

    async def _wait_for_url(self, timeout: int = 30) -> str:
        """Read process output until the tunnel URL appears.

        Uses a dedicated reader thread to avoid blocking-readline race
        conditions with Go binaries that buffer pipe output.
        """
        import threading

        url_pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        result: str | None = None
        error: str | None = None
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _reader() -> None:
            nonlocal result, error
            assert self._process is not None and self._process.stdout is not None
            try:
                for line in self._process.stdout:
                    logger.debug("cloudflared: %s", line.rstrip())
                    match = url_pattern.search(line)
                    if match:
                        result = match.group(0)
                        loop.call_soon_threadsafe(done.set)
                        return
                # stdout closed without finding URL
                error = "cloudflared exited without providing a tunnel URL"
            except Exception as exc:
                error = str(exc)
            loop.call_soon_threadsafe(done.set)

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()

        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except TimeoutError:
            raise TimeoutError("Timed out waiting for tunnel URL") from None

        if result:
            return result
        raise RuntimeError(error or "cloudflared exited unexpectedly")
