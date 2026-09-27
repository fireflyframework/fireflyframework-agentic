"""Benchmark loops must clean up without replacing pytest's current loop."""

import asyncio
import importlib

import pytest


@pytest.mark.parametrize("module_name", ["test_bench_http_pool", "test_bench_streaming_latency"])
def test_benchmark_loop_preserves_current_loop_and_finishes_async_generators(monkeypatch, module_name):
    module = importlib.import_module(f"tests.performance.{module_name}")
    changes = []
    finalized = []
    monkeypatch.setattr(asyncio.events, "set_event_loop", changes.append)

    async def unfinished_stream():
        try:
            yield "first chunk"
        finally:
            await asyncio.sleep(0)
            finalized.append(True)

    fixture = module.bench_loop.__wrapped__()
    loop = next(fixture)
    stream = unfinished_stream()

    async def consume_first_chunk():
        return await anext(stream)

    try:
        assert loop.run_until_complete(consume_first_chunk()) == "first chunk"
    finally:
        fixture.close()

    assert changes == [], "benchmark cleanup replaced pytest's current event loop"
    assert finalized == [True]
    assert loop.is_closed()
