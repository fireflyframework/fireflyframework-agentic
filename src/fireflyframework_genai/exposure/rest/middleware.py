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

"""Middleware for the REST exposure layer: request ID injection, CORS, rate limiting."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def add_request_id_middleware(app: Any) -> None:
    """Add middleware that injects a unique ``X-Request-ID`` header."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class RequestIDMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

    app.add_middleware(RequestIDMiddleware)


def add_cors_middleware(
    app: Any,
    *,
    allow_origins: list[str] | None = None,
    allow_methods: list[str] | None = None,
) -> None:
    """Add CORS middleware with configurable origins.

    Security Note:
        By default, this middleware uses a restrictive CORS policy (no origins allowed)
        for production security. You must explicitly specify allowed origins.

        **INSECURE (Development Only):**
            add_cors_middleware(app, allow_origins=["*"])

        **SECURE (Production):**
            add_cors_middleware(app, allow_origins=["https://myapp.com"])

    Args:
        app: The FastAPI or Starlette application.
        allow_origins: List of allowed origin URLs. Defaults to [] (no origins allowed).
        allow_methods: List of allowed HTTP methods. Defaults to standard methods.
    """
    from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]

    # Secure default: no origins allowed
    if allow_origins is None:
        allow_origins = []
        logger.warning(
            "CORS: No origins specified, defaulting to secure policy (no origins allowed). "
            "Set allow_origins=['*'] for development or specify exact origins for production."
        )

    # Warn about wildcard usage
    if "*" in allow_origins:
        logger.warning(
            "CORS: Wildcard origin ('*') allows requests from ANY domain. "
            "This is INSECURE for production. Specify exact origins instead."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )


class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Parameters:
        max_requests: Maximum requests per *window_seconds*.
        window_seconds: Time window for the rate limit.
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Return *True* if the request is within the rate limit."""
        now = time.monotonic()
        ts = self._timestamps.setdefault(key, [])
        ts[:] = [t for t in ts if now - t < self._window]
        if len(ts) >= self._max:
            return False
        ts.append(now)
        return True


def add_auth_middleware(
    app: Any,
    *,
    api_keys: list[str] | None = None,
    bearer_tokens: list[str] | None = None,
    auth_header: str = "Authorization",
    api_key_header: str = "X-API-Key",
    exclude_paths: list[str] | None = None,
) -> None:
    """Add authentication middleware to a FastAPI/Starlette application.

    Supports two authentication modes:

    * **API Key** -- checked via the ``X-API-Key`` header.
    * **Bearer Token** -- checked via the ``Authorization: Bearer <token>`` header.

    When both are configured, a request is accepted if *either* method succeeds.
    Unauthenticated requests receive a ``401 Unauthorized`` response.

    Parameters:
        app: The FastAPI or Starlette application.
        api_keys: List of valid API keys.
        bearer_tokens: List of valid bearer tokens.
        auth_header: Header name for bearer tokens.
        api_key_header: Header name for API keys.
        exclude_paths: URL paths excluded from auth (e.g. ``["/health"]``).
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    _api_keys = set(api_keys or [])
    _bearer_tokens = set(bearer_tokens or [])
    _exclude = set(exclude_paths or ["/health", "/health/ready", "/health/live", "/docs", "/openapi.json"])

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            if request.url.path in _exclude:
                return await call_next(request)

            # Try API key
            if _api_keys:
                key = request.headers.get(api_key_header, "")
                if key in _api_keys:
                    return await call_next(request)

            # Try bearer token
            if _bearer_tokens:
                auth_value = request.headers.get(auth_header, "")
                if auth_value.startswith("Bearer "):
                    token = auth_value[7:]
                    if token in _bearer_tokens:
                        return await call_next(request)

            # If no auth methods configured, allow all requests
            if not _api_keys and not _bearer_tokens:
                return await call_next(request)

            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
            )

    app.add_middleware(AuthMiddleware)


def add_rate_limit_middleware(
    app: Any,
    *,
    max_requests: int = 60,
    window_seconds: float = 60.0,
    key_func: Any | None = None,
) -> None:
    """Add rate-limiting middleware to a FastAPI/Starlette application.

    Parameters:
        app: The FastAPI or Starlette application.
        max_requests: Maximum requests per window per client.
        window_seconds: Rate limit window in seconds.
        key_func: Optional callable ``(Request) -> str`` for the rate key.
            Defaults to the client's IP address.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            rk = key_func(request) if key_func is not None else (request.client.host if request.client else "unknown")
            if not limiter.is_allowed(rk):
                return JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                )
            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)


def add_trace_propagation_middleware(app: Any) -> None:
    """Add W3C Trace Context propagation middleware.

    This middleware automatically extracts trace context from incoming HTTP
    requests (via ``traceparent`` and ``tracestate`` headers) and injects
    trace context into outgoing HTTP responses.

    This enables distributed tracing across microservices and external systems
    that support the W3C Trace Context standard.

    Parameters:
        app: The FastAPI or Starlette application.

    Example::

        from fastapi import FastAPI
        from fireflyframework_genai.exposure.rest.middleware import add_trace_propagation_middleware

        app = FastAPI()
        add_trace_propagation_middleware(app)

        # Now all requests will automatically participate in distributed traces

    See Also:
        - https://www.w3.org/TR/trace-context/
        - :func:`~fireflyframework_genai.observability.tracer.extract_trace_context`
        - :func:`~fireflyframework_genai.observability.tracer.inject_trace_context`
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    from fireflyframework_genai.observability.tracer import (
        extract_trace_context,
        inject_trace_context,
        trace_context_scope,
    )

    class TracePropagationMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            # Extract trace context from incoming request
            headers = dict(request.headers)
            span_context = extract_trace_context(headers)

            # Process request within trace context scope
            with trace_context_scope(span_context):
                response: Response = await call_next(request)

            # Inject trace context into outgoing response
            response_headers = dict(response.headers)
            inject_trace_context(response_headers)
            for key, value in response_headers.items():
                if key.lower() not in response.headers:
                    response.headers[key] = value

            return response

    app.add_middleware(TracePropagationMiddleware)
    logger.info("Trace propagation middleware enabled")
