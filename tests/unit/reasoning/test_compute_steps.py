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

"""Tests for the typed ComputeStep discriminated union and surrounding models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputedFacts,
    ComputeObservation,
    ComputePlan,
    ConvertStep,
    JoinStep,
    LookupStep,
    SqlRunStep,
    StepRef,
    VerifyStep,
)


class TestStepRef:
    def test_step_ref_with_path(self):
        ref = StepRef(step_id="s1", path="$.rows[*].id")
        assert ref.step_id == "s1"
        assert ref.path == "$.rows[*].id"

    def test_step_ref_without_path(self):
        ref = StepRef(step_id="s1")
        assert ref.path is None


class TestSqlRunStep:
    def test_minimal(self):
        step = SqlRunStep(id="s1", sql="SELECT 1", rationale="smoke test")
        assert step.kind == "sql_run"
        assert step.params == {}

    def test_with_params(self):
        step = SqlRunStep(
            id="s2",
            sql="SELECT name FROM employees WHERE manager_id = :mid",
            params={"mid": StepRef(step_id="s1", path="$.rows[0].id")},
            rationale="find direct reports",
        )
        assert "mid" in step.params


class TestArithStep:
    def test_valid_op(self):
        step = ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s2", path="$.rows")], rationale="count rows")
        assert step.op == "count"

    def test_rejects_unknown_op(self):
        with pytest.raises(ValidationError):
            ArithStep(id="a1", op="mean_of_logs", inputs=[], rationale="x")  # noqa


class TestComputePlanDiscriminator:
    def test_plan_round_trip_through_dict(self):
        plan = ComputePlan(
            goal="count reports",
            steps=[
                SqlRunStep(id="s1", sql="SELECT id FROM employees WHERE name='Javier'", rationale="lookup id"),
                SqlRunStep(
                    id="s2",
                    sql="SELECT name FROM employees WHERE manager_id = :mid",
                    params={"mid": StepRef(step_id="s1", path="$.rows[0].id")},
                    rationale="reports",
                ),
                ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s2", path="$.rows")], rationale="count"),
            ],
        )
        as_dict = plan.model_dump()
        rebuilt = ComputePlan.model_validate(as_dict)
        assert [s.kind for s in rebuilt.steps] == ["sql_run", "sql_run", "arith"]
        assert isinstance(rebuilt.steps[2], ArithStep)


class TestComputeObservation:
    def test_success(self):
        obs = ComputeObservation(
            step_id="s1", success=True, output={"rows": [{"id": 18}], "columns": ["id"]}, citations=["doc1#0"]
        )
        assert obs.success and obs.error is None

    def test_failure(self):
        obs = ComputeObservation(step_id="s1", success=False, output=None, citations=[], error="boom")
        assert not obs.success and obs.error == "boom"


class TestComputedFacts:
    def test_values_and_citations(self):
        facts = ComputedFacts(
            values={"direct_reports_count": 4, "direct_reports": ["Ana", "Luis", "Pia", "Tom"]},
            citations=["org_chart.pdf#p3"],
        )
        assert facts.values["direct_reports_count"] == 4
        assert facts.citations == ["org_chart.pdf#p3"]


class TestAllStepKindsParse:
    def test_join_lookup_convert_verify(self):
        steps = [
            JoinStep(
                id="j1",
                left=StepRef(step_id="s1", path="$.rows"),
                right_sql="SELECT id, name FROM employees",
                on={"id": "id"},
                select=["name"],
                rationale="join names",
            ),
            LookupStep(id="l1", chunk_id="doc#0", rationale="cite source"),
            ConvertStep(id="c1", value=1000.0, from_unit="USD", to_unit="EUR", rationale="convert"),
            VerifyStep(
                id="v1",
                claim="4 direct reports",
                against=[StepRef(step_id="s2", path="$.rows"), StepRef(step_id="l1")],
                rationale="cross-check",
            ),
        ]
        kinds = [s.kind for s in steps]
        assert kinds == ["join", "lookup", "convert", "verify"]
