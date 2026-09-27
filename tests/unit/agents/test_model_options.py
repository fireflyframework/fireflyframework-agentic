"""Portable settings must follow the model selected for each invocation."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import CacheMiddleware
from fireflyframework_agentic.agents.cache import ResultCache
from fireflyframework_agentic.agents.decorators import firefly_agent
from fireflyframework_agentic.models import ModelOptions, ModelOptionsError


def _agent(seen, **kwargs):
    def respond(messages, info):
        seen.append(dict(info.model_settings or {}))
        return ModelResponse(parts=[TextPart("done")])

    async def stream(messages, info):
        seen.append(dict(info.model_settings or {}))
        yield "done"

    return FireflyAgent(
        "portable",
        model=FunctionModel(respond, stream_function=stream),
        auto_register=False,
        default_middleware=False,
        **kwargs,
    )


@pytest.mark.parametrize("mode", ["async", "sync", "buffered", "incremental"])
async def test_options_merge_for_every_run_mode_without_mutating_defaults(mode):
    seen = []
    agent = _agent(seen, model_options=ModelOptions(max_tokens=100, temperature=0.2))
    options = ModelOptions(max_tokens=200)
    if mode == "async":
        await agent.run("hello", model_options=options)
    elif mode == "sync":
        agent.run_sync("hello", model_options=options)
    else:
        async with await agent.run_stream("hello", model_options=options, streaming_mode=mode) as stream:
            async for _ in stream.stream_text():
                pass
    await agent.run("again")
    assert seen == [
        {"max_tokens": 200, "temperature": 0.2},
        {"max_tokens": 100, "temperature": 0.2},
    ]


async def test_explicit_none_clears_an_inherited_portable_option():
    seen = []
    agent = _agent(seen, model_options=ModelOptions(max_tokens=100, temperature=0.2))
    await agent.run("hello", model_options=ModelOptions(temperature=None))
    assert seen == [{"max_tokens": 100}]


async def test_run_native_settings_override_portable_settings():
    seen = []
    agent = _agent(seen, model_settings={"max_tokens": 50}, model_options=ModelOptions(max_tokens=100))
    await agent.run("hello")
    await agent.run("hello", model_options=ModelOptions(max_tokens=200), model_settings={"max_tokens": 300})
    assert seen == [{"max_tokens": 100}, {"max_tokens": 300}]


async def test_decorator_passes_portable_options_to_the_agent():
    seen = []

    def respond(messages, info):
        seen.append(info.model_settings)
        return ModelResponse(parts=[TextPart("done")])

    @firefly_agent(
        "decorated", model=FunctionModel(respond), model_options=ModelOptions(max_tokens=77), auto_register=False
    )
    def instructions(ctx):
        return "Answer briefly."

    await instructions.run("hello")
    assert seen == [{"max_tokens": 77}]


@pytest.mark.parametrize("mode", ["async", "sync", "buffered", "incremental"])
async def test_invalid_options_fail_before_request_and_unwind_middleware(mode):
    seen = []
    errors = []

    class ErrorObserver:
        async def on_error(self, context, exc):
            errors.append(exc)

    agent = _agent(seen, middleware=[ErrorObserver()])
    with pytest.raises(ModelOptionsError) as error:
        options = ModelOptions(store_responses=True)
        if mode == "async":
            await agent.run("hello", model_options=options)
        elif mode == "sync":
            agent.run_sync("hello", model_options=options)
        else:
            await agent.run_stream("hello", model_options=options, streaming_mode=mode)
    assert seen == []
    assert errors == [error.value]


async def test_cache_distinguishes_portable_options_and_does_not_mask_invalid_controls():
    seen = []
    agent = _agent(seen, middleware=[CacheMiddleware(cache=ResultCache())])
    await agent.run("same", model_options=ModelOptions(max_tokens=100))
    await agent.run("same", model_options=ModelOptions(max_tokens=200))
    await agent.run("same", model_options=ModelOptions(max_tokens=100))
    with pytest.raises(ModelOptionsError):
        await agent.run("same", model_options=ModelOptions(store_responses=True))
    assert seen == [{"max_tokens": 100}, {"max_tokens": 200}]


async def test_shared_cache_distinguishes_agents_portable_defaults():
    seen = []
    cache = ResultCache()
    first = _agent(seen, model_options=ModelOptions(max_tokens=100), middleware=[CacheMiddleware(cache=cache)])
    second = _agent(seen, model_options=ModelOptions(max_tokens=200), middleware=[CacheMiddleware(cache=cache)])
    await first.run("same")
    await second.run("same")
    await first.run("same")
    assert seen == [{"max_tokens": 100}, {"max_tokens": 200}]
