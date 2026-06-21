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

"""Reasoning routes structured calls through the FireflyAgent stack.

Previously a reasoning pattern's structured calls were made on a bare ephemeral
``pydantic_ai.Agent``, bypassing the source agent's middleware chain, 429 retry
and model settings. Now, when the agent is a ``FireflyAgent``, the structured
call is routed through ``agent.run(output_type=...)`` so it inherits the stack.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.middleware import MiddlewareContext
from fireflyframework_agentic.reasoning.chain_of_thought import ChainOfThoughtPattern


@pytest.mark.asyncio
async def test_structured_reasoning_calls_flow_through_middleware():
    seen = {"before": 0, "after": 0}

    class RecordingMW:
        async def before_run(self, context: MiddlewareContext) -> None:
            seen["before"] += 1

        async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
            seen["after"] += 1
            return result

    # TestModel auto-fabricates valid instances of each requested output_type.
    agent = FireflyAgent(
        "reason-mw",
        model=TestModel(),
        middleware=[RecordingMW()],
        default_middleware=False,
        auto_register=False,
    )
    # The pattern's own termination behavior with TestModel is irrelevant here;
    # we only care that its structured calls passed through the middleware chain.
    with contextlib.suppress(Exception):
        await ChainOfThoughtPattern(max_steps=2).execute(agent, "think about it")

    # Structured calls were observed by the agent's middleware chain — proving
    # they no longer bypass the FireflyAgent stack.
    assert seen["before"] >= 1
    assert seen["after"] >= 1
