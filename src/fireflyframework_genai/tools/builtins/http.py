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

"""Built-in HTTP request tool.

Sends HTTP requests using httpx with connection pooling (if available),
or falls back to :mod:`urllib.request` if httpx is not installed.
Connection pooling significantly improves performance by reusing TCP connections.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import urllib.request
from collections.abc import Sequence
from typing import Any

from fireflyframework_genai.tools.base import BaseTool, GuardProtocol, ParameterSpec

logger = logging.getLogger(__name__)

# Check if httpx is available for connection pooling

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None


class HttpTool(BaseTool):
    """Execute HTTP requests (GET, POST, PUT, DELETE) with connection pooling.

    Uses httpx with connection pooling when available, providing significant
    performance improvements by reusing TCP connections. Falls back to urllib
    if httpx is not installed.

    Parameters:
        timeout: Request timeout in seconds.
        default_headers: Headers sent with every request.
        guards: Optional guard chain.
        use_pool: Whether to use connection pooling (requires httpx).
        pool_size: Maximum number of connections in the pool.
        pool_max_keepalive: Maximum number of idle connections to keep alive.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        guards: Sequence[GuardProtocol] = (),
        use_pool: bool = True,
        pool_size: int = 100,
        pool_max_keepalive: int = 20,
    ) -> None:
        super().__init__(
            "http",
            description="Send HTTP requests (GET, POST, PUT, DELETE)",
            tags=["http", "web"],
            guards=guards,
            parameters=[
                ParameterSpec(name="url", type_annotation="str", description="Request URL", required=True),
                ParameterSpec(
                    name="method", type_annotation="str", description="HTTP method", required=False, default="GET"
                ),
                ParameterSpec(
                    name="body", type_annotation="str | None", description="Request body", required=False, default=None
                ),
                ParameterSpec(
                    name="headers",
                    type_annotation="dict[str, str]",
                    description="Additional headers",
                    required=False,
                    default=None,
                ),
            ],
        )
        self._timeout = timeout
        self._default_headers = default_headers or {}
        self._use_pool = use_pool and HTTPX_AVAILABLE

        # Create httpx client with connection pooling
        if self._use_pool:
            import httpx as _httpx  # already verified available via HTTPX_AVAILABLE

            limits = _httpx.Limits(
                max_connections=pool_size,
                max_keepalive_connections=pool_max_keepalive,
            )
            self._client: Any = _httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                follow_redirects=True,
            )
            logger.info(
                "HttpTool initialized with connection pooling (pool_size=%d, max_keepalive=%d)",
                pool_size,
                pool_max_keepalive,
            )
        else:
            self._client = None
            if use_pool and not HTTPX_AVAILABLE:
                logger.warning("Connection pooling requested but httpx not available. Install with: pip install httpx")

    async def close(self) -> None:
        """Close the HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _execute(self, **kwargs: Any) -> dict[str, Any]:
        url: str = kwargs["url"]
        method: str = kwargs.get("method", "GET").upper()
        body: str | None = kwargs.get("body")
        headers: dict[str, str] = {**self._default_headers, **kwargs.get("headers", {})}

        if self._client is not None:
            # Use httpx with connection pooling
            return await self._do_request_httpx(url, method, body, headers)
        else:
            # Fallback to urllib
            return await asyncio.to_thread(self._do_request_urllib, url, method, body, headers)

    async def _do_request_httpx(
        self, url: str, method: str, body: str | None, headers: dict[str, str]
    ) -> dict[str, Any]:
        """Perform the async HTTP request using httpx with connection pooling."""
        assert self._client is not None

        response = await self._client.request(
            method=method,
            url=url,
            content=body.encode("utf-8") if body else None,
            headers=headers,
        )

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": response.text,
        }

    def _do_request_urllib(self, url: str, method: str, body: str | None, headers: dict[str, str]) -> dict[str, Any]:
        """Perform the blocking HTTP request using urllib in a thread."""
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            response_body = resp.read().decode("utf-8")
            return {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": response_body,
            }
