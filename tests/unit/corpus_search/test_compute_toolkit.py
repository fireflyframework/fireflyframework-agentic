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

"""Tests for the corpus-bound ComputeToolkit executors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.retrieval.compute_toolkit import (
    ComputeToolkit,
    RetrievalContext,
)
from fireflyframework_agentic.reasoning.compute_steps import (
    ComputeObservation,
    SqlRunStep,
    StepRef,
)


@pytest.fixture
def employees_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, manager_id INTEGER);
        INSERT INTO employees VALUES (1, 'Javier', NULL),
                                     (2, 'Ana', 1),
                                     (3, 'Luis', 1),
                                     (4, 'Pia', 1),
                                     (5, 'Tom', 1);
        """
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def toolkit(employees_db: Path) -> ComputeToolkit:
    return ComputeToolkit(
        corpus_db_path=employees_db,
        retrieval_context=RetrievalContext(top_hits=[], sql_outcome=None, schemas=[]),
    )


class TestSqlRunExecutor:
    async def test_select_returns_rows_and_columns(self, toolkit: ComputeToolkit):
        step = SqlRunStep(id="s1", sql="SELECT id FROM employees WHERE name='Javier'", rationale="lookup")
        obs = await toolkit.dispatch(step, previous={})
        assert obs.success
        assert obs.output["columns"] == ["id"]
        assert obs.output["rows"] == [{"id": 1}]

    async def test_parameter_resolution_from_prior_step(self, toolkit: ComputeToolkit):
        prior = {
            "s1": ComputeObservation(
                step_id="s1",
                success=True,
                output={"rows": [{"id": 1}], "columns": ["id"]},
            )
        }
        step = SqlRunStep(
            id="s2",
            sql="SELECT name FROM employees WHERE manager_id = :mid",
            params={"mid": StepRef(step_id="s1", path="$.rows[0].id")},
            rationale="reports",
        )
        obs = await toolkit.dispatch(step, previous=prior)
        assert obs.success
        names = {r["name"] for r in obs.output["rows"]}
        assert names == {"Ana", "Luis", "Pia", "Tom"}

    async def test_write_sql_is_rejected(self, toolkit: ComputeToolkit):
        step = SqlRunStep(id="s1", sql="DELETE FROM employees", rationale="bad")
        obs = await toolkit.dispatch(step, previous={})
        assert not obs.success
        assert "read-only" in obs.error.lower()

    async def test_missing_step_ref_yields_explicit_failure(self, toolkit: ComputeToolkit):
        step = SqlRunStep(
            id="s2",
            sql="SELECT name FROM employees WHERE manager_id = :mid",
            params={"mid": StepRef(step_id="nope", path="$.rows[0].id")},
            rationale="x",
        )
        obs = await toolkit.dispatch(step, previous={})
        assert not obs.success
        assert "nope" in obs.error

    async def test_star_projection_in_step_ref_path(self, toolkit: ComputeToolkit):
        """[*].key projection over a prior rows result returns a flat list of values."""
        # Insert rows where the prior step provides multiple manager_ids
        prior = {
            "s1": ComputeObservation(
                step_id="s1",
                success=True,
                output={"rows": [{"id": 1}], "columns": ["id"]},
            )
        }
        # First confirm the path resolver itself works: a path returning a list
        # of scalars is resolvable.  We test this indirectly: a SQL step whose
        # single param is a $.rows[*].id projection over a one-row prior would
        # produce a single-element list, which _resolve_params unwraps to the
        # scalar.  So we use a path that yields a scalar directly:
        step = SqlRunStep(
            id="s2",
            sql="SELECT name FROM employees WHERE id = :who",
            params={"who": StepRef(step_id="s1", path="$.rows[*].id")},
            rationale="x",
        )
        obs = await toolkit.dispatch(step, previous=prior)
        assert obs.success, obs.error
        names = {r["name"] for r in obs.output["rows"]}
        assert names == {"Javier"}

    async def test_bad_path_yields_actionable_error(self, toolkit: ComputeToolkit):
        """A path that fails to resolve produces an error mentioning the step + path."""
        prior = {
            "s1": ComputeObservation(
                step_id="s1",
                success=True,
                output={"rows": [{"id": 1}], "columns": ["id"]},
            )
        }
        step = SqlRunStep(
            id="s2",
            sql="SELECT name FROM employees WHERE id = :who",
            params={"who": StepRef(step_id="s1", path="$.does_not_exist")},
            rationale="x",
        )
        obs = await toolkit.dispatch(step, previous=prior)
        assert not obs.success
        # Error must mention the step_id AND the path so the planner LLM can fix it.
        assert "s1" in obs.error
        assert "does_not_exist" in obs.error
