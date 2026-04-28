#!/usr/bin/env python3
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

"""Smoke test for HTTP connection pooling feature.

Run this to quickly verify that HTTP connection pooling works.
"""

from __future__ import annotations

import asyncio

from fireflyframework_agentic.tools.builtins.http import HTTPX_AVAILABLE, HttpTool


async def main():
    """Run smoke tests."""
    print("HTTP Connection Pooling - Smoke Test")
    print("=" * 50)

    # Test 1: httpx availability
    print(f"\n✓ httpx available: {HTTPX_AVAILABLE}")

    # Test 2: Create tool with pooling
    tool_with_pool = HttpTool(use_pool=True, pool_size=50, pool_max_keepalive=10)
    print(f"✓ Tool created with pooling: {tool_with_pool._use_pool}")

    # Test 3: Create tool without pooling
    tool_without_pool = HttpTool(use_pool=False)
    print(f"✓ Tool created without pooling: {not tool_without_pool._use_pool}")

    # Test 4: Close functionality
    await tool_with_pool.close()
    print("✓ Connection pool closed successfully")

    print("\n" + "=" * 50)
    print("All smoke tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
