#!/usr/bin/env python3
# Copyright 2026 Firefly Software Foundation
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

"""Exercise HttpTool pooling against an HTTP echo service.

The default endpoint is https://httpbin.org. Override HTTP_EXAMPLE_BASE_URL
with a compatible local service for offline verification. Uses the public tool
execute API; failed requests fail the demonstration, and every pool is closed.
Timings describe this run only, not a guaranteed performance improvement.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fireflyframework_agentic.tools.builtins.http import HttpTool

BASE_URL = os.getenv("HTTP_EXAMPLE_BASE_URL", "https://httpbin.org").rstrip("/")


async def request(tool: HttpTool, path: str, **kwargs: Any) -> dict[str, Any]:
    result = await tool.execute(url=f"{BASE_URL}{path}", headers=kwargs.pop("headers", {}), **kwargs)
    if not 200 <= result["status"] < 300:
        raise RuntimeError(f"HTTP request failed: {result['status']}")
    return result


async def demo_with_connection_pooling() -> None:
    tool = HttpTool(use_pool=True, pool_size=10, pool_max_keepalive=5)
    try:
        start = time.perf_counter()
        for index in range(5):
            result = await request(tool, f"/get?request={index}")
            print(f"Sequential request {index}: HTTP {result['status']}")
        print(f"Five sequential requests: {time.perf_counter() - start:.3f}s")
        start = time.perf_counter()
        results = await asyncio.gather(*(request(tool, f"/get?request={i}") for i in range(5)))
        print(
            f"Five concurrent requests: {time.perf_counter() - start:.3f}s; statuses={[r['status'] for r in results]}"
        )
        posted = await request(
            tool, "/post", method="POST", body='{"value": 123}', headers={"Content-Type": "application/json"}
        )
        print(f"POST response: {posted['body']}")
        headers = await request(tool, "/headers", headers={"X-Example": "firefly-pooling"})
        print(f"Header echo: {headers['body']}")
    finally:
        await tool.close()


async def demo_comparison_pooled_vs_non_pooled() -> None:
    timings = {}
    for pooled in (True, False):
        tool = HttpTool(use_pool=pooled)
        try:
            start = time.perf_counter()
            for index in range(5):
                await request(tool, f"/get?request={index}")
            timings["pooled" if pooled else "urllib"] = time.perf_counter() - start
        finally:
            await tool.close()
    print(f"Five successful requests per implementation, seconds: {timings}")


async def main() -> None:
    await demo_with_connection_pooling()
    await demo_comparison_pooled_vs_non_pooled()


if __name__ == "__main__":
    asyncio.run(main())
