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

"""retryable() must apply on the path pydantic-ai actually calls.

The agent invokes a tool through ``pydantic_handler()`` (built from
``execute`` / ``execute_with_ctx``). Wrapping ``_execute`` ensures retries apply
there too — not only on a direct ``tool.execute()`` call.
"""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.tools.decorators import firefly_tool, retryable


@pytest.mark.asyncio
async def test_retryable_applies_through_the_pydantic_handler():
    calls = {"n": 0}

    @retryable(max_retries=2, backoff=0.001)
    @firefly_tool("flaky-handler", auto_register=False)
    async def flaky(**kwargs: Any) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    handler = flaky.pydantic_handler()  # the exact callable the agent registers
    result = await handler()
    assert result == "ok"
    assert calls["n"] == 3  # retried via the handler path, not bypassed
