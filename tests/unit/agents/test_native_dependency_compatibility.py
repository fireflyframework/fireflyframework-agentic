# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline contracts for native model wrappers across dependency upgrades."""

from __future__ import annotations

import asyncio
import gc

import pytest
from pydantic_ai.concurrency import ConcurrencyLimiter
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.concurrency import ConcurrencyLimitedModel, limit_model_concurrency
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.config import FireflyAgenticConfig
from fireflyframework_agentic.observability.usage import UsageTracker


@pytest.mark.parametrize("wrap", [ConcurrencyLimitedModel, limit_model_concurrency])
@pytest.mark.parametrize("mode", ["buffered", "incremental"])
@pytest.mark.parametrize("ending", ["complete", "break", "error", "cancel"])
def test_native_limiter_releases_stream_capacity(wrap, mode: str, ending: str) -> None:
    loop_errors = []
    # Keep the handler installed through async-generator shutdown, where
    # unfinished iterator cleanup can fail after the stream context has closed.
    with asyncio.Runner() as runner:
        runner.get_loop().set_exception_handler(lambda _loop, context: loop_errors.append(context))
        runner.run(_exercise_limited_stream(wrap, mode, ending))
    assert loop_errors == []


async def _exercise_limited_stream(wrap, mode: str, ending: str) -> None:
    limiter = ConcurrencyLimiter(max_running=1)
    first_chunk = asyncio.Event()

    async def stream(messages, info):
        for index in range(8):
            if ending == "error" and index == 4:
                raise RuntimeError("local stream failure")
            yield f"{index} "
            await asyncio.sleep(0.03)

    async def respond(messages, info):
        return ModelResponse(parts=[TextPart("capacity available")])

    agent = FireflyAgent(
        "native-limiter",
        model=wrap(FunctionModel(respond, stream_function=stream), limiter=limiter),
        auto_register=False,
        default_middleware=False,
        config=FireflyAgenticConfig(cost_tracking_enabled=False),
    )

    async def consume() -> None:
        # A timeout enters the native stream on a separate task, exercising the
        # cross-task cleanup contract fixed in PydanticAI 2.53.
        async with await agent.run_stream("hello", streaming_mode=mode, timeout=1) as result:
            chunks = result.stream_tokens() if mode == "incremental" else result.stream_text()
            async for _ in chunks:
                assert limiter.available_count == 0
                first_chunk.set()
                if ending == "break":
                    break

    task = asyncio.create_task(consume())
    try:
        if ending == "cancel":
            await asyncio.wait_for(first_chunk.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif ending == "error":
            with pytest.raises(RuntimeError, match="local stream failure"):
                await asyncio.wait_for(task, timeout=2)
        else:
            await asyncio.wait_for(task, timeout=2)
        assert limiter.available_count == 1
        following = await asyncio.wait_for(agent.run("again"), timeout=1)
        assert following.output == "capacity available"
        # Early iteration exit can otherwise defer async-generator failures
        # until loop shutdown, after an apparently successful capacity check.
        gc.collect()
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_native_fallback_counts_rejected_response_usage_once_in_firefly_ledger() -> None:
    calls = []

    async def primary(messages, info):
        calls.append("primary")
        return ModelResponse(
            parts=[TextPart("reject")],
            usage=RequestUsage(input_tokens=11, output_tokens=3, cache_read_tokens=2, cache_write_tokens=4),
        )

    async def backup(messages, info):
        calls.append("backup")
        return ModelResponse(
            parts=[TextPart("accepted")],
            usage=RequestUsage(input_tokens=17, output_tokens=5, cache_read_tokens=3, cache_write_tokens=6),
        )

    def reject_response(response: ModelResponse) -> bool:
        return response.parts[0].content == "reject"

    tracker = UsageTracker(resolver=lambda context: 0.0)
    agent = FireflyAgent(
        "native-fallback",
        model=FallbackModel(
            FunctionModel(primary, model_name="primary"),
            FunctionModel(backup, model_name="backup"),
            fallback_on=reject_response,
        ),
        auto_register=False,
        default_middleware=False,
        config=FireflyAgenticConfig(cost_tracking_enabled=True),
        usage_tracker=tracker,
    )
    result = await agent.run("hello")
    assert result.output == "accepted"
    assert calls == ["primary", "backup"]
    assert (result.usage.input_tokens, result.usage.output_tokens) == (28, 8)
    assert (result.usage.cache_read_tokens, result.usage.cache_write_tokens) == (5, 10)
    assert result.usage.requests == 1
    assert len(result.response.failed_attempts) == 1
    assert len(tracker.records) == 1
    record = tracker.records[0]
    assert (record.input_tokens, record.output_tokens, record.total_tokens) == (28, 8, 36)
    assert (record.cache_read_tokens, record.cache_creation_tokens) == (5, 10)
    assert record.request_count == 1


def test_incremental_early_exit_closes_iterators_before_loop_shutdown() -> None:
    errors = []

    async def stream(messages, info):
        for index in range(8):
            yield f"{index} "
            await asyncio.sleep(0.03)

    async def exercise_exits() -> None:
        for mode in ("buffered", "incremental"):
            for ending in ("complete", "break", "error", "cancel"):
                limiter = ConcurrencyLimiter(max_running=1)
                agent = FireflyAgent(
                    "early-exit",
                    model=ConcurrencyLimitedModel(FunctionModel(stream_function=stream), limiter=limiter),
                    auto_register=False,
                    default_middleware=False,
                    config=FireflyAgenticConfig(cost_tracking_enabled=False),
                )
                try:
                    async with await agent.run_stream("hello", streaming_mode=mode) as result:
                        chunks = (
                            result.stream_tokens() if mode == "incremental" else result.stream_text(debounce_by=None)
                        )
                        async for _ in chunks:
                            if ending == "break":
                                break
                            if ending == "error":
                                raise ValueError("consumer stopped")
                            if ending == "cancel":
                                raise asyncio.CancelledError
                except (ValueError, asyncio.CancelledError):
                    pass
                assert limiter.available_count == 1

    with asyncio.Runner() as runner:
        runner.get_loop().set_exception_handler(lambda _loop, context: errors.append(context))
        runner.run(exercise_exits())
    assert errors == []
