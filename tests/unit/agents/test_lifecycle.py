"""Tests for agents/lifecycle.py."""

from __future__ import annotations

from fireflyframework_agentic.agents.lifecycle import AgentLifecycle


class TestAgentLifecycle:
    async def test_init_hooks_run_in_order(self) -> None:
        lc = AgentLifecycle()
        order: list[int] = []
        lc.on_init(lambda: order.append(1))
        lc.on_init(lambda: order.append(2))
        await lc.run_init()
        assert order == [1, 2]

    async def test_async_hooks(self) -> None:
        lc = AgentLifecycle()
        called = []

        async def async_hook() -> None:
            called.append("async")

        lc.on_warmup(async_hook)
        await lc.run_warmup()
        assert called == ["async"]

    async def test_shutdown_hooks(self) -> None:
        lc = AgentLifecycle()
        called = []
        lc.on_shutdown(lambda: called.append("shut"))
        await lc.run_shutdown()
        assert called == ["shut"]

    async def test_hook_error_does_not_prevent_others(self) -> None:
        lc = AgentLifecycle()
        called: list[str] = []

        def failing() -> None:
            raise RuntimeError("fail")

        lc.on_init(failing)
        lc.on_init(lambda: called.append("ok"))
        await lc.run_init()
        assert called == ["ok"]

    def test_on_init_returns_hook(self) -> None:
        lc = AgentLifecycle()
        hook = lambda: None  # noqa: E731
        assert lc.on_init(hook) is hook
