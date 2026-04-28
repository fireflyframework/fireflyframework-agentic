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

"""Structured trace model for reasoning patterns.

Every reasoning pattern emits ordered :class:`ReasoningStep` objects into a
:class:`ReasoningTrace`.  These traces make all reasoning inspectable for
observability, explainability, and debugging.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ThoughtStep(BaseModel):
    """Internal reasoning or analysis produced by the LLM."""

    kind: Literal["thought"] = "thought"
    content: str
    confidence: float | None = None


class ActionStep(BaseModel):
    """A tool invocation selected by the reasoning pattern."""

    kind: Literal["action"] = "action"
    tool_name: str
    tool_args: dict[str, Any] = {}


class ObservationStep(BaseModel):
    """Result of a tool invocation or external input."""

    kind: Literal["observation"] = "observation"
    content: str
    source: str = ""


class ReflectionStep(BaseModel):
    """Self-critique produced during reflective reasoning."""

    kind: Literal["reflection"] = "reflection"
    critique: str
    should_retry: bool = False


class PlanStep(BaseModel):
    """A planned sub-task within a larger goal decomposition."""

    kind: Literal["plan"] = "plan"
    description: str
    sub_steps: list[str] = []


# Union type for all step kinds
ReasoningStep = ThoughtStep | ActionStep | ObservationStep | ReflectionStep | PlanStep


class ReasoningTrace(BaseModel):
    """Ordered collection of reasoning steps produced by a single pattern execution."""

    pattern_name: str
    steps: list[ReasoningStep] = []
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def add_step(self, step: ReasoningStep) -> None:
        """Append a step to the trace."""
        self.steps.append(step)

    def complete(self) -> None:
        """Mark the trace as completed with the current UTC time."""
        self.completed_at = datetime.now(UTC)


class ReasoningResult(BaseModel, Generic[T]):
    """Final outcome of a reasoning pattern execution.

    Generic over ``T`` so that patterns can declare their output type.
    When ``T`` is not specified, ``output`` accepts any value for
    backward compatibility.
    """

    output: T = None  # type: ignore[assignment]
    trace: ReasoningTrace
    steps_taken: int = 0
    success: bool = True
