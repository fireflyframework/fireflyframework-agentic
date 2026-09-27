"""Synchronous runs keep middleware context alive through the model and cleanup."""

import asyncio
from contextvars import ContextVar

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from fireflyframework_agentic.agents import FireflyAgent


@pytest.mark.parametrize("inside_event_loop", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_sync_run_uses_one_context_for_middleware_model_and_cleanup(inside_event_loop, fail):
    marker = ContextVar("sync_test_marker", default="outside")
    observed = []

    class ContextMiddleware:
        async def before_run(self, context):
            context.metadata["token"] = marker.set("inside")

        async def after_run(self, context, result):
            marker.reset(context.metadata["token"])
            return result

        async def on_error(self, context, exc):
            marker.reset(context.metadata["token"])

    def respond(messages, info):
        observed.append(marker.get())
        if fail:
            raise RuntimeError("model failed")
        return ModelResponse(parts=[TextPart("done")])

    agent = FireflyAgent(
        "sync-context",
        model=FunctionModel(respond),
        middleware=[ContextMiddleware()],
        default_middleware=False,
        auto_register=False,
    )

    def run():
        if fail:
            with pytest.raises(RuntimeError, match="model failed"):
                agent.run_sync("hello")
        else:
            assert agent.run_sync("hello").output == "done"

    if inside_event_loop:

        async def caller():
            run()

        asyncio.run(caller(), loop_factory=asyncio.new_event_loop)
    else:
        run()
    assert observed == ["inside"]
    assert marker.get() == "outside"


@pytest.mark.parametrize("inside_event_loop", [False, True])
def test_repeated_sync_runs_retain_the_loop_and_copy_each_callers_context(inside_event_loop):
    caller_marker = ContextVar("caller_marker", default="missing")
    loops = []
    values = []

    async def respond(messages, info):
        loops.append(asyncio.get_running_loop())
        values.append(caller_marker.get())
        caller_marker.set("changed only inside model task")
        return ModelResponse(parts=[TextPart("done")])

    agent = FireflyAgent("persistent-sync", model=FunctionModel(respond), auto_register=False, default_middleware=False)

    def run():
        for value in ["first", "second", "third"]:
            token = caller_marker.set(value)
            try:
                assert agent.run_sync(value).output == "done"
                assert caller_marker.get() == value
            finally:
                caller_marker.reset(token)

    if inside_event_loop:

        async def caller():
            run()

        asyncio.run(caller(), loop_factory=asyncio.new_event_loop)
    else:
        run()
    assert values == ["first", "second", "third"]
    assert len({id(loop) for loop in loops}) == 1
    assert not loops[0].is_closed()


def test_reentrant_sync_run_fails_instead_of_blocking_its_owner_loop():
    from fireflyframework_agentic.exceptions import AgentError

    nested = FireflyAgent(
        "nested",
        model=FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("done")])),
        auto_register=False,
        default_middleware=False,
    )

    async def respond(messages, info):
        with pytest.raises(AgentError, match="await"):
            nested.run_sync("nested request")
        return ModelResponse(parts=[TextPart("outer done")])

    agent = FireflyAgent("outer", model=FunctionModel(respond), auto_register=False, default_middleware=False)
    assert agent.run_sync("outer request").output == "outer done"


def test_interrupted_sync_wait_cancels_the_running_model_task(monkeypatch):
    import threading

    started = threading.Event()
    cancelled = threading.Event()
    submitted = []
    original_submit = asyncio.run_coroutine_threadsafe

    async def respond(messages, info):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return ModelResponse(parts=[TextPart("unreachable")])

    def interrupt_wait(coro, loop):
        future = original_submit(coro, loop)
        submitted.append(future)

        class InterruptedWait:
            def result(self):
                assert started.wait(2), "model did not start"
                raise KeyboardInterrupt

            def cancel(self):
                return future.cancel()

        return InterruptedWait()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", interrupt_wait)
    agent = FireflyAgent("interruptible", model=FunctionModel(respond), auto_register=False, default_middleware=False)
    try:
        with pytest.raises(KeyboardInterrupt):
            agent.run_sync("wait for cancellation")
        assert cancelled.wait(2), "model kept running after its caller was interrupted"
    finally:
        for future in submitted:
            future.cancel()
        cancelled.wait(2)


def test_sync_agent_memory_hooks_use_a_separate_database_loop(monkeypatch):
    from types import SimpleNamespace

    from fireflyframework_agentic.memory import MemoryManager, database_store
    from tests.unit.memory.test_database_lifecycle import _LoopBoundDatabase

    pools = []
    agent_loops = []

    async def create_pool(*args, **kwargs):
        pool = _LoopBoundDatabase()
        pool.close = pool.close_pool
        pools.append(pool)
        return pool

    monkeypatch.setattr(database_store, "asyncpg", SimpleNamespace(create_pool=create_pool))
    memory = MemoryManager(store=database_store.PostgreSQLStore("postgresql://offline-test"))

    class FactMiddleware:
        async def before_run(self, context):
            memory.set_fact("request", context.prompt)

    async def respond(messages, info):
        agent_loops.append(asyncio.get_running_loop())
        return ModelResponse(parts=[TextPart(memory.get_fact("request"))])

    agent = FireflyAgent(
        "sync-memory",
        model=FunctionModel(respond),
        middleware=[FactMiddleware()],
        auto_register=False,
        default_middleware=False,
    )
    try:
        assert agent.run_sync("first").output == "first"
        assert agent.run_sync("second").output == "second"
        assert len(pools) == 1
        assert all(loop is not pools[0].loop for loop in agent_loops)
    finally:
        memory.close()
    assert pools[0].closed
