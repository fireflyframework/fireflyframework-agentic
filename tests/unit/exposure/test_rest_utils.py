"""Tests for REST exposure utilities — auth middleware and WebSocket router."""

from __future__ import annotations


class TestAuthMiddleware:
    def test_add_auth_middleware_callable(self):
        """Verify add_auth_middleware is a callable that accepts expected args."""
        import inspect

        from fireflyframework_agentic.exposure.rest.middleware import add_auth_middleware

        sig = inspect.signature(add_auth_middleware)
        params = list(sig.parameters.keys())
        assert "app" in params
        assert "api_keys" in params or "bearer_tokens" in params


class TestWebSocketRouter:
    def test_create_websocket_router_callable(self):
        """Verify the factory function exists and is callable."""
        from fireflyframework_agentic.exposure.rest.websocket import create_websocket_router

        assert callable(create_websocket_router)
