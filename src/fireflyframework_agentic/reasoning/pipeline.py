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

"""Reasoning pipeline for composing multiple patterns sequentially.

A :class:`ReasoningPipeline` is itself a :class:`ReasoningPattern`, so
pipelines can be nested inside other pipelines.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from fireflyframework_agentic.reasoning.trace import (
    ReasoningResult,
    ReasoningTrace,
)
from fireflyframework_agentic.types import AgentLike, UserContent

# Use a structural (duck-typing) check rather than importing the Protocol
# to avoid circular dependencies.

logger = logging.getLogger(__name__)


class ReasoningPipeline:
    """Execute reasoning patterns in sequence, piping each output as the next input.

    Parameters:
        patterns: Ordered sequence of pattern instances (anything with
            ``async execute(agent, input, **kwargs) -> ReasoningResult``).
        name: Name for the composite pipeline.
    """

    def __init__(self, patterns: Sequence[Any], *, name: str = "pipeline") -> None:
        self._patterns = list(patterns)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, agent: AgentLike, input: str | Sequence[UserContent], **kwargs: Any) -> ReasoningResult:
        """Run each pattern in order.

        The output of pattern *N* becomes the input for pattern *N+1*.
        The first pattern receives the original (possibly multimodal) input;
        subsequent patterns receive the string output of the previous pattern.

        If a ``memory`` keyword argument is provided (a
        :class:`~fireflyframework_agentic.memory.manager.MemoryManager`),
        it is passed through to **every** pattern's ``execute()`` call.
        Because each pattern forks the memory into its own working-memory
        scope (``reasoning:<pattern_name>``), subsequent patterns can read
        earlier patterns' outputs via the shared backing store.

        The returned :class:`ReasoningResult` contains a merged trace
        spanning all patterns.
        """
        t_start = time.monotonic()
        pattern_names = [getattr(p, "name", type(p).__name__) for p in self._patterns]
        logger.info(
            "Pipeline '%s': starting %d patterns: %s", self._name, len(self._patterns), " → ".join(pattern_names)
        )
        merged_trace = ReasoningTrace(pattern_name=self._name)
        total_steps = 0
        current_input: str | Sequence[UserContent] = input

        for i, pattern in enumerate(self._patterns):
            p_name = getattr(pattern, "name", type(pattern).__name__)
            logger.info("Pipeline '%s': running pattern %d/%d '%s'", self._name, i + 1, len(self._patterns), p_name)
            t0 = time.monotonic()
            result: ReasoningResult = await pattern.execute(agent, current_input, **kwargs)
            logger.info(
                "Pipeline '%s': pattern '%s' completed in %.1fs (%d steps)",
                self._name,
                p_name,
                time.monotonic() - t0,
                result.steps_taken,
            )
            merged_trace.steps.extend(result.trace.steps)
            total_steps += result.steps_taken
            # After the first pattern, output is always a string
            current_input = str(result.output) if result.output is not None else str(current_input)

        logger.info(
            "Pipeline '%s': completed in %.1fs (%d total steps)", self._name, time.monotonic() - t_start, total_steps
        )
        merged_trace.complete()
        return ReasoningResult(
            output=current_input,
            trace=merged_trace,
            steps_taken=total_steps,
            success=True,
        )

    def __repr__(self) -> str:
        return f"ReasoningPipeline(name={self._name!r}, patterns={len(self._patterns)})"
