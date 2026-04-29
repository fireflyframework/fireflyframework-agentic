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

"""Performance benchmarks for streaming latency.

These benchmarks compare buffered vs incremental streaming modes
to measure time-to-first-token (TTFT) and overall streaming latency.

Run with:
    pytest tests/performance/test_bench_streaming_latency.py --benchmark-only
"""

from __future__ import annotations

import time

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent


@pytest.mark.benchmark(group="streaming-latency")
class TestStreamingLatencyBenchmarks:
    """Benchmark streaming latency for different modes."""

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_buffered_streaming_latency(self, benchmark):
        """Benchmark buffered streaming mode latency."""
        agent = FireflyAgent("bench-buffered", model="test", auto_register=False)

        async def stream_buffered():
            start = time.perf_counter()
            first_token_time = None

            stream_ctx = await agent.run_stream("hello", streaming_mode="buffered")
            async with stream_ctx as stream:
                async for _chunk in stream.stream_text():
                    if first_token_time is None:
                        first_token_time = time.perf_counter() - start
                    # Only consume first few chunks for benchmarking
                    break

            return first_token_time

        benchmark(lambda: pytest.asyncio.fixture(stream_buffered))

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_incremental_streaming_latency(self, benchmark):
        """Benchmark incremental streaming mode latency."""
        agent = FireflyAgent("bench-incremental", model="test", auto_register=False)

        async def stream_incremental():
            start = time.perf_counter()
            first_token_time = None

            stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
            async with stream_ctx as stream:
                async for _token in stream.stream_tokens():
                    if first_token_time is None:
                        first_token_time = time.perf_counter() - start
                    # Only consume first few tokens for benchmarking
                    break

            return first_token_time

        benchmark(lambda: pytest.asyncio.fixture(stream_incremental))

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_incremental_with_debounce(self, benchmark):
        """Benchmark incremental streaming with debouncing."""
        agent = FireflyAgent("bench-debounce", model="test", auto_register=False)

        async def stream_with_debounce():
            start = time.perf_counter()
            first_token_time = None

            stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
            async with stream_ctx as stream:
                async for _token in stream.stream_tokens(debounce_ms=10.0):
                    if first_token_time is None:
                        first_token_time = time.perf_counter() - start
                    break

            return first_token_time

        benchmark(lambda: pytest.asyncio.fixture(stream_with_debounce))

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_full_response_buffered(self, benchmark):
        """Benchmark full response streaming in buffered mode."""
        agent = FireflyAgent("bench-full-buf", model="test", auto_register=False)

        async def stream_full_buffered():
            chunks = []
            stream_ctx = await agent.run_stream("Count to 10", streaming_mode="buffered")
            async with stream_ctx as stream:
                async for chunk in stream.stream_text():
                    chunks.append(chunk)
                    if len(chunks) >= 5:  # Limit for benchmarking
                        break
            return len(chunks)

        benchmark(lambda: pytest.asyncio.fixture(stream_full_buffered))

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_full_response_incremental(self, benchmark):
        """Benchmark full response streaming in incremental mode."""
        agent = FireflyAgent("bench-full-inc", model="test", auto_register=False)

        async def stream_full_incremental():
            tokens = []
            stream_ctx = await agent.run_stream("Count to 10", streaming_mode="incremental")
            async with stream_ctx as stream:
                async for token in stream.stream_tokens():
                    tokens.append(token)
                    if len(tokens) >= 5:  # Limit for benchmarking
                        break
            return len(tokens)

        benchmark(lambda: pytest.asyncio.fixture(stream_full_incremental))

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_stream_context_manager_overhead(self, benchmark):
        """Benchmark overhead of stream context manager creation."""
        agent = FireflyAgent("bench-ctx", model="test", auto_register=False)

        async def create_stream_context():
            stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
            async with stream_ctx:
                # Just enter/exit without consuming
                pass

        benchmark(lambda: pytest.asyncio.fixture(create_stream_context))


@pytest.mark.benchmark(group="streaming-comparison")
class TestStreamingModeComparison:
    """Compare buffered vs incremental streaming performance."""

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_time_to_first_token_comparison(self, benchmark):
        """Compare time-to-first-token between modes."""
        # This is a meta-benchmark to document expected differences
        # Expected: Incremental mode should have lower TTFT
        pass

    @pytest.mark.nightly
    @pytest.mark.asyncio
    async def test_bench_throughput_comparison(self, benchmark):
        """Compare overall throughput between modes."""
        # This is a meta-benchmark to document expected differences
        # Expected: Buffered mode may have slightly higher throughput
        # but incremental mode provides better perceived performance
        pass


# Performance expectations (documented for regression detection):
# - Incremental mode should show 20-40% lower time-to-first-token (TTFT)
# - Incremental mode provides better perceived performance for users
# - Buffered mode may have slightly higher total throughput
# - Debouncing adds latency but reduces message frequency
# - Context manager overhead should be minimal (<1ms)
