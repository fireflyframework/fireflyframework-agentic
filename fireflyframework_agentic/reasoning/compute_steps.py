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

"""Typed step kinds for the corpus compute stage.

Each variant is the *input* schema for one deterministic operation.  The
toolkit dispatches on ``kind`` to a Python executor that produces a
matching :class:`ComputeObservation` with structured ``output`` and
explicit ``citations``.

Together with :class:`~fireflyframework_agentic.reasoning.trace.ReasoningTrace`,
the steps form the user-facing 'how this was computed' trail.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class StepRef(BaseModel):
    """Reference to a prior step's structured output.

    ``path`` is an optional dotted/JSONPath-style accessor into the
    referenced observation's ``output``.  Resolution is performed by the
    toolkit at dispatch time.
    """

    step_id: str
    path: str | None = None


class _ComputeStepBase(BaseModel):
    """Shared metadata on every compute step."""

    id: str
    rationale: str = ""


class SqlRunStep(_ComputeStepBase):
    kind: Literal["sql_run"] = "sql_run"
    sql: str
    params: dict[str, StepRef | Any] = Field(default_factory=dict)


class ArithStep(_ComputeStepBase):
    kind: Literal["arith"] = "arith"
    op: Literal["count", "sum", "avg", "min", "max", "percent", "diff", "ratio"]
    inputs: list[StepRef | Any] = Field(default_factory=list)


class JoinStep(_ComputeStepBase):
    kind: Literal["join"] = "join"
    left: StepRef
    right_sql: str
    on: dict[str, str]
    select: list[str]


class ConvertStep(_ComputeStepBase):
    kind: Literal["convert"] = "convert"
    value: StepRef | Any
    from_unit: str
    to_unit: str


class LookupStep(_ComputeStepBase):
    kind: Literal["lookup"] = "lookup"
    chunk_id: str


class VerifyStep(_ComputeStepBase):
    kind: Literal["verify"] = "verify"
    claim: str
    against: list[StepRef] = Field(default_factory=list)


ComputeStep = Annotated[
    SqlRunStep | ArithStep | JoinStep | ConvertStep | LookupStep | VerifyStep,
    Field(discriminator="kind"),
]


class ComputePlan(BaseModel):
    """Goal-bound ordered list of typed compute steps.

    Distinct from :class:`~fireflyframework_agentic.reasoning.models.ReasoningPlan`
    so the planner LLM is forced into the discriminated-union shape with
    structured outputs.
    """

    goal: str
    steps: list[ComputeStep] = Field(default_factory=list)


class ComputeObservation(BaseModel):
    """Structured result of executing one ComputeStep."""

    step_id: str
    success: bool
    output: Any = None
    citations: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> ComputeObservation:
        if self.success and self.error is not None:
            raise ValueError("error must be None when success is True")
        return self


class ComputedFacts(BaseModel):
    """Final structured output of :class:`CorpusComputePattern`.

    ``values`` carries named computed scalars or rows the narrator can
    quote verbatim.  ``citations`` aggregates every chunk_id that grounded
    any step in the trace.
    """

    values: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
