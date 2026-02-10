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

"""FastAPI application factory for exposing Firefly agents over REST.

Call :func:`create_genai_app` to get a fully-configured FastAPI instance
with agent, health, and streaming endpoints.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: Any) -> AsyncIterator[None]:
    """FastAPI lifespan: plugin discovery, warmup, OTel, and shutdown."""
    from fireflyframework_genai.config import get_config

    cfg = get_config()

    # -- Startup -----------------------------------------------------------
    if cfg.plugin_auto_discover:
        from fireflyframework_genai.plugin import PluginDiscovery

        result = PluginDiscovery.discover_all()
        logger.info(
            "Plugins: %d loaded, %d failed",
            len(result.successful),
            len(result.failed),
        )

    from fireflyframework_genai.agents.lifecycle import agent_lifecycle
    from fireflyframework_genai.reasoning.prompts import register_reasoning_prompts

    register_reasoning_prompts()
    await agent_lifecycle.run_warmup()

    if cfg.observability_enabled:
        from fireflyframework_genai.observability.exporters import configure_exporters

        configure_exporters(
            otlp_endpoint=cfg.otlp_endpoint,
            console=cfg.otlp_endpoint is None,
        )

    yield

    # -- Shutdown ----------------------------------------------------------
    await agent_lifecycle.run_shutdown()


def create_genai_app(
    *,
    title: str = "Firefly GenAI",
    version: str = "0.1.0",
    cors: bool = True,
    request_id: bool = True,
    rate_limit: bool | dict[str, Any] = False,
) -> Any:
    """Create a FastAPI application with agent exposure endpoints.

    Parameters:
        title: Application title for OpenAPI docs.
        version: Application version.
        cors: Enable CORS middleware.
        request_id: Enable request-ID injection middleware.
        rate_limit: Enable rate-limiting middleware.  Pass ``True`` for
            defaults or a dict with ``max_requests``, ``window_seconds``,
            and/or ``key_func`` to customise behaviour.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    # Lazy imports — FastAPI and its dependencies are optional extras.
    # Importing inside the factory ensures the core framework can be used
    # without installing the [rest] extra.
    from fastapi import FastAPI  # type: ignore[import-not-found]

    from fireflyframework_genai.exposure.rest.health import create_health_router
    from fireflyframework_genai.exposure.rest.middleware import (
        add_cors_middleware,
        add_rate_limit_middleware,
        add_request_id_middleware,
    )
    from fireflyframework_genai.exposure.rest.router import create_agent_router

    app = FastAPI(title=title, version=version, lifespan=_lifespan)

    # Middleware
    if cors:
        add_cors_middleware(app)
    if request_id:
        add_request_id_middleware(app)
    if rate_limit:
        rl_kwargs = rate_limit if isinstance(rate_limit, dict) else {}
        add_rate_limit_middleware(app, **rl_kwargs)

    # Auto-wire auth middleware from config
    from fireflyframework_genai.config import get_config

    cfg = get_config()
    if cfg.auth_api_keys or cfg.auth_bearer_tokens:
        from fireflyframework_genai.exposure.rest.middleware import add_auth_middleware

        add_auth_middleware(
            app,
            api_keys=cfg.auth_api_keys,
            bearer_tokens=cfg.auth_bearer_tokens,
        )

    # Routers
    app.include_router(create_health_router())
    app.include_router(create_agent_router())

    # WebSocket
    from fireflyframework_genai.exposure.rest.websocket import create_websocket_router

    app.include_router(create_websocket_router())

    return app
