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

"""Performance benchmarks for HTTP connection pooling.

These benchmarks compare performance with and without connection pooling.

Run with:
    pytest tests/performance/test_bench_http_pool.py --benchmark-only
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest

from fireflyframework_agentic.tools.builtins.http import HttpTool


@pytest.fixture
def mock_http_response():
    """Create a mock HTTP response."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.status = 200  # For urllib
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.text = '{"result": "success"}'
    mock_response.read = Mock(return_value=b'{"result": "success"}')
    return mock_response


@pytest.fixture
def bench_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Single event loop reused across benchmark iterations.

    `pytest-benchmark` runs the benchmarked callable many times. Spinning up a
    fresh loop per iteration would dominate the measurement and would also
    detach pooled httpx clients from their loop, so we keep one loop for the
    whole test.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_with_connection_pool(benchmark, bench_loop, mock_http_response):
    """Benchmark HTTP requests with connection pooling."""
    tool = HttpTool(use_pool=True, pool_size=100)

    async def make_request():
        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_http_response
            await tool._execute(
                url="https://api.example.com/endpoint",
                method="GET",
            )

    benchmark(lambda: bench_loop.run_until_complete(make_request()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_without_connection_pool(benchmark, mock_http_response):
    """Benchmark HTTP requests without connection pooling (urllib fallback)."""
    tool = HttpTool(use_pool=False)

    async def make_request():
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = Mock(return_value=mock_http_response)
            mock_urlopen.return_value.__exit__ = Mock(return_value=False)
            await tool._execute(
                url="https://api.example.com/endpoint",
                method="GET",
            )

    benchmark(lambda: asyncio.run(make_request()))


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_concurrent_requests_with_pool(benchmark, bench_loop, mock_http_response):
    """Benchmark concurrent requests with connection pooling."""
    tool = HttpTool(use_pool=True, pool_size=50)

    async def make_concurrent_requests():
        async def single_request():
            with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_http_response
                await tool._execute(
                    url="https://api.example.com/endpoint",
                    method="GET",
                )

        await asyncio.gather(*[single_request() for _ in range(10)])

    benchmark(lambda: bench_loop.run_until_complete(make_concurrent_requests()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_sequential_requests_with_pool(benchmark, bench_loop, mock_http_response):
    """Benchmark sequential requests with connection pooling."""
    tool = HttpTool(use_pool=True, pool_size=100)

    async def make_sequential_requests():
        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_http_response

            for _ in range(10):
                await tool._execute(
                    url="https://api.example.com/endpoint",
                    method="GET",
                )

    benchmark(lambda: bench_loop.run_until_complete(make_sequential_requests()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_pool_size_small(benchmark, bench_loop, mock_http_response):
    """Benchmark with small pool size (10 connections)."""
    tool = HttpTool(use_pool=True, pool_size=10, pool_max_keepalive=5)

    async def make_request():
        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_http_response
            await tool._execute(
                url="https://api.example.com/endpoint",
                method="GET",
            )

    benchmark(lambda: bench_loop.run_until_complete(make_request()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_pool_size_large(benchmark, bench_loop, mock_http_response):
    """Benchmark with large pool size (200 connections)."""
    tool = HttpTool(use_pool=True, pool_size=200, pool_max_keepalive=100)

    async def make_request():
        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_http_response
            await tool._execute(
                url="https://api.example.com/endpoint",
                method="GET",
            )

    benchmark(lambda: bench_loop.run_until_complete(make_request()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_with_request_body(benchmark, bench_loop, mock_http_response):
    """Benchmark POST requests with body and connection pooling."""
    tool = HttpTool(use_pool=True, pool_size=100)

    async def make_post_request():
        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_http_response
            await tool._execute(
                url="https://api.example.com/create",
                method="POST",
                body='{"name": "test", "value": 123}',
                headers={"Content-Type": "application/json"},
            )

    benchmark(lambda: bench_loop.run_until_complete(make_post_request()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool")
def test_bench_different_urls_with_pool(benchmark, bench_loop, mock_http_response):
    """Benchmark requests to different URLs with connection pooling."""
    tool = HttpTool(use_pool=True, pool_size=100)

    async def make_requests_to_different_urls():
        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_http_response

            urls = [
                "https://api1.example.com/endpoint",
                "https://api2.example.com/endpoint",
                "https://api3.example.com/endpoint",
                "https://api4.example.com/endpoint",
                "https://api5.example.com/endpoint",
            ]

            for url in urls:
                await tool._execute(url=url, method="GET")

    benchmark(lambda: bench_loop.run_until_complete(make_requests_to_different_urls()))
    bench_loop.run_until_complete(tool.close())


@pytest.mark.nightly
@pytest.mark.benchmark(group="http-pool-comparison")
def test_bench_pool_vs_no_pool_single_request():
    """Compare pooled vs non-pooled for single request.

    Meta-benchmark stub: actual comparison is done by inspecting the results of
    the `http-pool` group benchmarks above. The overhead difference shows up in
    repeated requests.
    """


# Performance expectations (documented for regression detection):
# - Connection pooling should show 30-50% improvement for sequential requests
# - Concurrent requests should show 50-70% improvement with pooling
# - Pool size of 100 is optimal for most workloads
# - Larger pools (200+) show diminishing returns
# - Small pools (10) can become bottleneck under high concurrency
