"""Tests for observability/decorators.py."""

from __future__ import annotations

from fireflyframework_agentic.observability.decorators import metered, traced


class TestTracedDecorator:
    async def test_async_function_traced(self) -> None:
        @traced("test-span")
        async def my_func() -> str:
            return "ok"

        result = await my_func()
        assert result == "ok"

    def test_sync_function_traced(self) -> None:
        @traced("sync-span")
        def my_func() -> str:
            return "ok"

        result = my_func()
        assert result == "ok"


class TestMeteredDecorator:
    async def test_async_function_metered(self) -> None:
        @metered("test-op")
        async def my_func() -> str:
            return "metered"

        result = await my_func()
        assert result == "metered"

    def test_sync_function_metered(self) -> None:
        @metered("sync-op")
        def my_func() -> int:
            return 42

        result = my_func()
        assert result == 42
