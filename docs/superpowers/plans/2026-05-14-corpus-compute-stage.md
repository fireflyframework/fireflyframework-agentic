# Corpus answer compute stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a deterministic compute-and-verify stage between corpus retrieval and answer narration so calculations are reliable and a structured steps trail rides along on every `Answer`.

**Architecture:** Add a generic `CorpusComputePattern` to `fireflyframework_agentic/reasoning/` (built on the existing `AbstractReasoningPattern` infra). It runs an LLM-generated plan of typed `ComputeStep` items dispatched to a corpus-bound `ComputeToolkit` whose Python executors (sql_run / arith / join / convert / lookup / verify) do the actual work. `CorpusAgent.query()` calls the new stage after the existing parallel retrieval and forwards `ComputedFacts` to a tightened narrator (Sonnet, computation-forbidden). The resulting `ReasoningTrace` is returned on the `Answer`.

**Tech Stack:** Python 3.13, pydantic v2 (discriminated unions, structured outputs), pydantic-ai (`FireflyAgent`), sqlite3 (stdlib, existing `_connect` helper in `rag/retrieval/sql.py:94`), OpenTelemetry (existing helpers in `rag/_telemetry.py`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-14-corpus-compute-stage-design.md`

---

## File structure

**New files:**

```
fireflyframework_agentic/
├── reasoning/
│   ├── compute_steps.py         — ComputeStep union, StepRef, ComputeObservation, ComputedFacts
│   └── corpus_compute.py        — CorpusComputePattern
└── rag/retrieval/
    ├── compute_toolkit.py       — ComputeToolkit, RetrievalContext, executors
    └── compute_stage.py         — CorpusComputeStage adapter

tests/
├── unit/reasoning/
│   ├── test_compute_steps.py
│   └── test_corpus_compute.py
├── unit/corpus_search/
│   └── test_compute_toolkit.py
└── integration/
    └── test_corpus_agent_compute.py
```

**Modified files:**

```
fireflyframework_agentic/
├── reasoning/__init__.py                — re-export new symbols
├── rag/agent.py                         — wire compute stage into query()
├── rag/retrieval/answerer.py            — narrator role, accept ComputedFacts, forbid recomputation
├── rag/_telemetry.py                    — add compute span helpers
└── tools/builtins/corpus_rag.py         — surface trace + computed_facts in MCP response
```

---

## Task 0: Branch from main

**Files:** none (working tree state)

- [ ] **Step 1: Confirm clean working tree**

Run: `git status`
Expected: `nothing to commit, working tree clean`

- [ ] **Step 2: Confirm on main and up to date**

Run: `git switch main && git pull --ff-only`
Expected: `Already up to date.` or fast-forward summary

- [ ] **Step 3: Create the feature branch**

Run: `git switch -c feat/corpus-compute-stage`
Expected: `Switched to a new branch 'feat/corpus-compute-stage'`

---

## Task 1: ComputeStep types + ComputedFacts model

**Files:**
- Create: `fireflyframework_agentic/reasoning/compute_steps.py`
- Test: `tests/unit/reasoning/test_compute_steps.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/reasoning/test_compute_steps.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/reasoning/test_compute_steps.py -v`
Expected: collection error (`ModuleNotFoundError: fireflyframework_agentic.reasoning.compute_steps`)

- [ ] **Step 3: Implement `compute_steps.py`**

Create `fireflyframework_agentic/reasoning/compute_steps.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

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

from pydantic import BaseModel, Field


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


class ComputedFacts(BaseModel):
    """Final structured output of :class:`CorpusComputePattern`.

    ``values`` carries named computed scalars or rows the narrator can
    quote verbatim.  ``citations`` aggregates every chunk_id that grounded
    any step in the trace.
    """

    values: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Re-export from `reasoning/__init__.py`**

Edit `fireflyframework_agentic/reasoning/__init__.py`. Add the new imports next to the existing ones and to `__all__`:

```python
from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputedFacts,
    ComputeObservation,
    ComputePlan,
    ComputeStep,
    ConvertStep,
    JoinStep,
    LookupStep,
    SqlRunStep,
    StepRef,
    VerifyStep,
)
```

Add the same names to `__all__` (alphabetised to match the existing convention).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/reasoning/test_compute_steps.py -v`
Expected: all tests pass

- [ ] **Step 6: Run the existing reasoning test suite to confirm no regression**

Run: `uv run pytest tests/unit/reasoning -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add fireflyframework_agentic/reasoning/compute_steps.py \
        fireflyframework_agentic/reasoning/__init__.py \
        tests/unit/reasoning/test_compute_steps.py
git commit -m "feat(reasoning): add ComputeStep types and ComputedFacts model"
```

---

## Task 2: ComputeToolkit skeleton + `_run_sql` executor

**Files:**
- Create: `fireflyframework_agentic/rag/retrieval/compute_toolkit.py`
- Test: `tests/unit/corpus_search/test_compute_toolkit.py`

- [ ] **Step 1: Write the failing test for the SQL executor**

Create `tests/unit/corpus_search/test_compute_toolkit.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py -v`
Expected: collection error (`ModuleNotFoundError: ...compute_toolkit`)

- [ ] **Step 3: Implement the toolkit with SQL executor and dispatch shell**

Create `fireflyframework_agentic/rag/retrieval/compute_toolkit.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Corpus-bound deterministic executors for the compute stage.

Each public dispatch returns a :class:`ComputeObservation` capturing the
inputs (via the step model on the trace), the structured output, and the
citations that ground the result.  No executor here calls an LLM.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.sql import (
    SqlRetrievalOutcome,
    TargetSchema,
    _connect,
)
from fireflyframework_agentic.reasoning.compute_steps import (
    ComputeObservation,
    ComputeStep,
    SqlRunStep,
    StepRef,
)


@dataclass(slots=True)
class RetrievalContext:
    """Inputs the toolkit needs from the prior retrieval stage."""

    top_hits: Sequence[ChunkHit] = field(default_factory=list)
    sql_outcome: SqlRetrievalOutcome | None = None
    schemas: list[TargetSchema] = field(default_factory=list)


_WRITE_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)


class ComputeToolkit:
    """Deterministic executors for the corpus compute stage."""

    def __init__(self, *, corpus_db_path: Path, retrieval_context: RetrievalContext) -> None:
        self._db_path = corpus_db_path
        self._ctx = retrieval_context

    async def dispatch(
        self,
        step: ComputeStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        """Execute one typed step and return its observation.

        Dispatch is by ``step.kind``.  Each executor is responsible for
        catching its own exceptions and returning a failed observation
        with a meaningful ``error`` message.
        """
        try:
            if isinstance(step, SqlRunStep):
                return await self._run_sql(step, previous)
            return ComputeObservation(
                step_id=step.id,
                success=False,
                output=None,
                error=f"unsupported step kind: {step.kind}",
            )
        except Exception as exc:  # noqa: BLE001 — observations encapsulate failure
            return ComputeObservation(
                step_id=step.id,
                success=False,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _run_sql(
        self,
        step: SqlRunStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        if _WRITE_SQL.search(step.sql):
            return ComputeObservation(
                step_id=step.id, success=False, error="sql is not read-only (only SELECT is allowed)"
            )
        params = _resolve_params(step.params, previous)
        if isinstance(params, str):  # error message
            return ComputeObservation(step_id=step.id, success=False, error=params)

        conn = _connect(self._db_path)
        try:
            cursor = conn.execute(step.sql, params)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]
        finally:
            conn.close()
        return ComputeObservation(
            step_id=step.id,
            success=True,
            output={"columns": columns, "rows": rows, "sql": step.sql},
        )


def _resolve_params(
    raw: dict[str, Any],
    previous: dict[str, ComputeObservation],
) -> dict[str, Any] | str:
    """Resolve StepRef placeholders against prior observations.

    Returns either the resolved dict or an error string explaining what
    could not be resolved.  Path syntax is intentionally minimal: dotted
    keys plus ``[N]`` indices and ``[*]`` for whole list extraction.
    """
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, StepRef):
            if value.step_id not in previous:
                return f"step '{value.step_id}' not found in prior observations"
            obs = previous[value.step_id]
            if not obs.success:
                return f"step '{value.step_id}' did not succeed; cannot reference it"
            resolved = _apply_path(obs.output, value.path) if value.path else obs.output
            if isinstance(resolved, list) and len(resolved) == 1:
                resolved = resolved[0]
            out[key] = resolved
        else:
            out[key] = value
    return out


def _apply_path(data: Any, path: str) -> Any:
    """Tiny JSONPath-ish accessor: ``$.foo.bar[0]``, ``$.rows[*].id``."""
    if not path or path == "$":
        return data
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\[\d+\]|\[\*\]", path)
    current: Any = data
    for tok in tokens:
        if tok.startswith("["):
            inner = tok[1:-1]
            if inner == "*":
                if not isinstance(current, list):
                    raise ValueError(f"[*] requires a list at this position, got {type(current).__name__}")
                current = list(current)
            else:
                current = current[int(inner)]
        else:
            current = current[tok] if isinstance(current, dict) else getattr(current, tok)
    return current
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py -v`
Expected: all four tests pass

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/compute_toolkit.py \
        tests/unit/corpus_search/test_compute_toolkit.py
git commit -m "feat(rag): ComputeToolkit with read-only SQL executor"
```

---

## Task 3: Toolkit `_run_arith` executor

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/compute_toolkit.py`
- Modify: `tests/unit/corpus_search/test_compute_toolkit.py`

- [ ] **Step 1: Add failing tests for arith**

Append to `tests/unit/corpus_search/test_compute_toolkit.py`:

```python
from fireflyframework_agentic.reasoning.compute_steps import ArithStep


class TestArithExecutor:
    async def test_count_resolves_step_ref(self, toolkit):
        prior = {
            "s1": ComputeObservation(
                step_id="s1",
                success=True,
                output={"rows": [{"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}], "columns": ["id"]},
            )
        }
        step = ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s1", path="$.rows")], rationale="x")
        obs = await toolkit.dispatch(step, previous=prior)
        assert obs.success
        assert obs.output == {"op": "count", "result": 4}

    async def test_sum_inline_values(self, toolkit):
        step = ArithStep(id="a1", op="sum", inputs=[1, 2, 3.5], rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert obs.success
        assert obs.output["result"] == 6.5

    async def test_percent_two_args(self, toolkit):
        step = ArithStep(id="a1", op="percent", inputs=[50, 200], rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert obs.success
        assert obs.output["result"] == 25.0

    async def test_ratio_div_by_zero(self, toolkit):
        step = ArithStep(id="a1", op="ratio", inputs=[1, 0], rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert not obs.success
        assert "zero" in obs.error.lower()

    async def test_sum_rejects_strings(self, toolkit):
        step = ArithStep(id="a1", op="sum", inputs=["a", "b"], rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert not obs.success
        assert "numeric" in obs.error.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py::TestArithExecutor -v`
Expected: 5 failures (`unsupported step kind: arith`)

- [ ] **Step 3: Implement arith executor**

Add to `compute_toolkit.py`. Import `ArithStep` at top with the other compute step imports. Extend `dispatch`:

```python
            if isinstance(step, ArithStep):
                return await self._run_arith(step, previous)
```

Add the method:

```python
    async def _run_arith(
        self,
        step: ArithStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        values = _flatten_inputs(step.inputs, previous)
        if isinstance(values, str):
            return ComputeObservation(step_id=step.id, success=False, error=values)

        if step.op == "count":
            return ComputeObservation(
                step_id=step.id, success=True, output={"op": "count", "result": len(values)}
            )

        try:
            nums = [float(v) for v in values]
        except (TypeError, ValueError) as exc:
            return ComputeObservation(
                step_id=step.id, success=False, error=f"arith requires numeric inputs: {exc}"
            )

        op = step.op
        try:
            if op == "sum":
                result: float = sum(nums)
            elif op == "avg":
                if not nums:
                    raise ZeroDivisionError("avg over empty list")
                result = sum(nums) / len(nums)
            elif op == "min":
                result = min(nums)
            elif op == "max":
                result = max(nums)
            elif op == "diff":
                if len(nums) != 2:
                    return ComputeObservation(
                        step_id=step.id, success=False, error="diff requires exactly 2 inputs"
                    )
                result = nums[0] - nums[1]
            elif op == "ratio":
                if len(nums) != 2:
                    return ComputeObservation(
                        step_id=step.id, success=False, error="ratio requires exactly 2 inputs"
                    )
                if nums[1] == 0:
                    return ComputeObservation(step_id=step.id, success=False, error="division by zero")
                result = nums[0] / nums[1]
            elif op == "percent":
                if len(nums) != 2:
                    return ComputeObservation(
                        step_id=step.id, success=False, error="percent requires exactly 2 inputs (part, whole)"
                    )
                if nums[1] == 0:
                    return ComputeObservation(step_id=step.id, success=False, error="division by zero")
                result = nums[0] / nums[1] * 100.0
            else:
                return ComputeObservation(step_id=step.id, success=False, error=f"unknown op: {op}")
        except ZeroDivisionError as exc:
            return ComputeObservation(step_id=step.id, success=False, error=str(exc))
        return ComputeObservation(step_id=step.id, success=True, output={"op": op, "result": result})
```

And add the flattening helper at module level near `_resolve_params`:

```python
def _flatten_inputs(
    raw: list[Any],
    previous: dict[str, ComputeObservation],
) -> list[Any] | str:
    """Resolve StepRef inputs into a flat list of leaf values.

    A reference whose resolved value is a list is flattened one level so
    arithmetic ops see a flat sequence regardless of whether the value
    came from inline data or a SQL rowset.  Returns an error string on
    unresolvable references.
    """
    out: list[Any] = []
    for item in raw:
        if isinstance(item, StepRef):
            if item.step_id not in previous:
                return f"step '{item.step_id}' not found in prior observations"
            obs = previous[item.step_id]
            if not obs.success:
                return f"step '{item.step_id}' did not succeed; cannot reference it"
            resolved = _apply_path(obs.output, item.path) if item.path else obs.output
            if isinstance(resolved, list):
                out.extend(resolved)
            else:
                out.append(resolved)
        else:
            out.append(item)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/compute_toolkit.py \
        tests/unit/corpus_search/test_compute_toolkit.py
git commit -m "feat(rag): ComputeToolkit arith executor"
```

---

## Task 4: Toolkit `_run_join`, `_run_convert`, `_run_lookup`, `_run_verify`

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/compute_toolkit.py`
- Modify: `tests/unit/corpus_search/test_compute_toolkit.py`

- [ ] **Step 1: Add failing tests for join, convert, lookup, verify**

Append to `tests/unit/corpus_search/test_compute_toolkit.py`:

```python
from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.reasoning.compute_steps import (
    ConvertStep,
    JoinStep,
    LookupStep,
    VerifyStep,
)


class TestJoinExecutor:
    async def test_join_on_left_rows(self, toolkit, employees_db):
        prior = {
            "s1": ComputeObservation(
                step_id="s1",
                success=True,
                output={"rows": [{"id": 2}, {"id": 3}], "columns": ["id"]},
            )
        }
        step = JoinStep(
            id="j1",
            left=StepRef(step_id="s1", path="$.rows"),
            right_sql="SELECT id, name FROM employees",
            on={"id": "id"},
            select=["name"],
            rationale="get names by id",
        )
        obs = await toolkit.dispatch(step, previous=prior)
        assert obs.success
        names = {r["name"] for r in obs.output["rows"]}
        assert names == {"Ana", "Luis"}


class TestConvertExecutor:
    async def test_currency_with_explicit_rate(self, toolkit):
        toolkit.set_conversion_rate("USD", "EUR", 0.9)
        step = ConvertStep(id="c1", value=1000.0, from_unit="USD", to_unit="EUR", rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert obs.success
        assert obs.output["result"] == pytest.approx(900.0)

    async def test_unknown_conversion_fails_explicitly(self, toolkit):
        step = ConvertStep(id="c1", value=1.0, from_unit="JPY", to_unit="EUR", rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert not obs.success
        assert "JPY" in obs.error and "EUR" in obs.error

    async def test_percent_to_decimal(self, toolkit):
        step = ConvertStep(id="c1", value=78.5, from_unit="percent", to_unit="decimal", rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert obs.success
        assert obs.output["result"] == pytest.approx(0.785)


class TestLookupExecutor:
    async def test_lookup_returns_chunk_content(self, employees_db, tmp_path):
        hit = ChunkHit(
            chunk_id="doc1#0",
            score=0.9,
            content="Javier manages four reports.",
            metadata={},
            source_path="org_chart.pdf",
        )
        tk = ComputeToolkit(
            corpus_db_path=employees_db,
            retrieval_context=RetrievalContext(top_hits=[hit], sql_outcome=None, schemas=[]),
        )
        step = LookupStep(id="l1", chunk_id="doc1#0", rationale="cite")
        obs = await tk.dispatch(step, previous={})
        assert obs.success
        assert obs.output["content"].startswith("Javier")
        assert obs.citations == ["doc1#0"]

    async def test_missing_chunk_fails(self, toolkit):
        step = LookupStep(id="l1", chunk_id="absent#0", rationale="x")
        obs = await toolkit.dispatch(step, previous={})
        assert not obs.success
        assert "absent#0" in obs.error


class TestVerifyExecutor:
    async def test_numeric_tolerance_match(self, toolkit):
        prior = {
            "a1": ComputeObservation(step_id="a1", success=True, output={"op": "count", "result": 4}),
            "l1": ComputeObservation(
                step_id="l1",
                success=True,
                output={"content": "Javier has 4 direct reports.", "source_path": "org_chart.pdf"},
                citations=["org_chart.pdf#p3"],
            ),
        }
        step = VerifyStep(
            id="v1",
            claim="4",
            against=[StepRef(step_id="a1", path="$.result"), StepRef(step_id="l1", path="$.content")],
            rationale="cross-check count",
        )
        obs = await toolkit.dispatch(step, previous=prior)
        assert obs.success
        assert obs.output["verdict"] == "match"
        assert "org_chart.pdf#p3" in obs.citations

    async def test_mismatch_returns_no_match(self, toolkit):
        prior = {
            "a1": ComputeObservation(step_id="a1", success=True, output={"op": "count", "result": 5}),
            "l1": ComputeObservation(
                step_id="l1", success=True, output={"content": "3 reports", "source_path": "x"}, citations=[]
            ),
        }
        step = VerifyStep(
            id="v1",
            claim="5",
            against=[StepRef(step_id="l1", path="$.content")],
            rationale="x",
        )
        obs = await toolkit.dispatch(step, previous=prior)
        assert obs.success
        assert obs.output["verdict"] == "no_match"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py -v`
Expected: failures in the four new classes

- [ ] **Step 3: Implement the four executors**

In `compute_toolkit.py`, add imports for the new step kinds at the top:

```python
from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputeObservation,
    ComputeStep,
    ConvertStep,
    JoinStep,
    LookupStep,
    SqlRunStep,
    StepRef,
    VerifyStep,
)
```

Extend `dispatch`:

```python
            if isinstance(step, JoinStep):
                return await self._run_join(step, previous)
            if isinstance(step, ConvertStep):
                return await self._run_convert(step, previous)
            if isinstance(step, LookupStep):
                return await self._run_lookup(step, previous)
            if isinstance(step, VerifyStep):
                return await self._run_verify(step, previous)
```

Add a constructor-side conversion table and a `set_conversion_rate` helper:

```python
    def __init__(self, *, corpus_db_path: Path, retrieval_context: RetrievalContext) -> None:
        self._db_path = corpus_db_path
        self._ctx = retrieval_context
        self._rates: dict[tuple[str, str], float] = {
            ("percent", "decimal"): 0.01,
            ("decimal", "percent"): 100.0,
        }
        # Time conversions are computed inline below.

    def set_conversion_rate(self, from_unit: str, to_unit: str, rate: float) -> None:
        """Register or override a unit conversion rate.

        Currency rates and any non-trivial conversion must be supplied
        explicitly by the caller (typically the corpus owner via config).
        """
        self._rates[(from_unit, to_unit)] = rate
```

Add the four executor methods:

```python
    async def _run_join(
        self,
        step: JoinStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        if step.left.step_id not in previous:
            return ComputeObservation(
                step_id=step.id, success=False, error=f"step '{step.left.step_id}' not found"
            )
        left_obs = previous[step.left.step_id]
        if not left_obs.success:
            return ComputeObservation(
                step_id=step.id, success=False, error=f"step '{step.left.step_id}' did not succeed"
            )
        left_rows = _apply_path(left_obs.output, step.left.path) if step.left.path else left_obs.output
        if not isinstance(left_rows, list):
            return ComputeObservation(
                step_id=step.id, success=False, error="join.left must reference a list of rows"
            )

        if _WRITE_SQL.search(step.right_sql):
            return ComputeObservation(step_id=step.id, success=False, error="right_sql must be read-only")

        conn = _connect(self._db_path)
        try:
            cursor = conn.execute(step.right_sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            right_rows = [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]
        finally:
            conn.close()

        # Index right by (left_col_value...) for an inner join
        left_cols = list(step.on.keys())
        right_cols = list(step.on.values())
        right_index: dict[tuple[Any, ...], dict[str, Any]] = {}
        for r in right_rows:
            try:
                key = tuple(r[c] for c in right_cols)
            except KeyError as exc:
                return ComputeObservation(
                    step_id=step.id, success=False, error=f"right_sql missing on-column {exc}"
                )
            right_index[key] = r

        joined: list[dict[str, Any]] = []
        for lr in left_rows:
            try:
                key = tuple(lr[c] for c in left_cols)
            except KeyError as exc:
                return ComputeObservation(
                    step_id=step.id, success=False, error=f"left rows missing on-column {exc}"
                )
            rr = right_index.get(key)
            if rr is None:
                continue
            merged = {**lr, **rr}
            joined.append({k: merged[k] for k in step.select if k in merged})
        return ComputeObservation(step_id=step.id, success=True, output={"rows": joined, "columns": step.select})

    async def _run_convert(
        self,
        step: ConvertStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        raw_value = step.value
        if isinstance(raw_value, StepRef):
            resolved = _resolve_params({"v": raw_value}, previous)
            if isinstance(resolved, str):
                return ComputeObservation(step_id=step.id, success=False, error=resolved)
            raw_value = resolved["v"]

        try:
            v = float(raw_value)
        except (TypeError, ValueError) as exc:
            return ComputeObservation(
                step_id=step.id, success=False, error=f"convert requires a numeric value: {exc}"
            )

        result = _try_time_conversion(v, step.from_unit, step.to_unit)
        if result is not None:
            return ComputeObservation(
                step_id=step.id,
                success=True,
                output={"result": result, "from_unit": step.from_unit, "to_unit": step.to_unit},
            )
        rate = self._rates.get((step.from_unit, step.to_unit))
        if rate is None:
            return ComputeObservation(
                step_id=step.id,
                success=False,
                error=f"no conversion rate registered for {step.from_unit} -> {step.to_unit}",
            )
        return ComputeObservation(
            step_id=step.id,
            success=True,
            output={"result": v * rate, "from_unit": step.from_unit, "to_unit": step.to_unit},
        )

    async def _run_lookup(
        self,
        step: LookupStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        for h in self._ctx.top_hits:
            if h.chunk_id == step.chunk_id:
                return ComputeObservation(
                    step_id=step.id,
                    success=True,
                    output={"content": h.content, "source_path": h.source_path},
                    citations=[h.chunk_id],
                )
        return ComputeObservation(
            step_id=step.id, success=False, error=f"chunk_id '{step.chunk_id}' not in top_hits"
        )

    async def _run_verify(
        self,
        step: VerifyStep,
        previous: dict[str, ComputeObservation],
    ) -> ComputeObservation:
        evidence: list[str] = []
        citations: list[str] = []
        match = False
        claim = step.claim.strip()
        for ref in step.against:
            if ref.step_id not in previous:
                return ComputeObservation(
                    step_id=step.id, success=False, error=f"step '{ref.step_id}' not found"
                )
            obs = previous[ref.step_id]
            if not obs.success:
                continue
            citations.extend(obs.citations)
            piece = _apply_path(obs.output, ref.path) if ref.path else obs.output
            evidence.append(str(piece))
            if _claim_matches(claim, piece):
                match = True
        verdict = "match" if match else "no_match"
        return ComputeObservation(
            step_id=step.id,
            success=True,
            output={"verdict": verdict, "claim": claim, "evidence": evidence},
            citations=sorted(set(citations)),
        )
```

Add the small helpers at module level:

```python
_TIME_TO_SECONDS = {
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3600.0,
    "days": 86400.0,
    "weeks": 86400.0 * 7,
}


def _try_time_conversion(value: float, from_unit: str, to_unit: str) -> float | None:
    if from_unit in _TIME_TO_SECONDS and to_unit in _TIME_TO_SECONDS:
        return value * _TIME_TO_SECONDS[from_unit] / _TIME_TO_SECONDS[to_unit]
    return None


def _claim_matches(claim: str, evidence: Any) -> bool:
    """Tiered match: numeric tolerance first, then case-insensitive substring."""
    try:
        c = float(claim)
        e = float(evidence)
        return abs(c - e) <= max(1e-9, abs(c) * 1e-6)
    except (TypeError, ValueError):
        pass
    return claim.lower() in str(evidence).lower()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/compute_toolkit.py \
        tests/unit/corpus_search/test_compute_toolkit.py
git commit -m "feat(rag): ComputeToolkit join/convert/lookup/verify executors"
```

---

## Task 5: `CorpusComputePattern` (planner + execution loop)

**Files:**
- Create: `fireflyframework_agentic/reasoning/corpus_compute.py`
- Test: `tests/unit/reasoning/test_corpus_compute.py`
- Modify: `fireflyframework_agentic/reasoning/__init__.py`

- [ ] **Step 1: Write the failing pattern tests**

Create `tests/unit/reasoning/test_corpus_compute.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for CorpusComputePattern.

The planner LLM is stubbed; the toolkit is a fake that returns canned
observations.  We verify plan execution order, trace shape, and
ComputedFacts assembly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputedFacts,
    ComputeObservation,
    ComputePlan,
    ComputeStep,
    SqlRunStep,
    StepRef,
)
from fireflyframework_agentic.reasoning.corpus_compute import CorpusComputePattern
from fireflyframework_agentic.reasoning.trace import ActionStep, ObservationStep, ThoughtStep


@dataclass
class _MockResult:
    output: Any


class _PlanAgent:
    """Stubs the planner LLM: returns a fixed ComputePlan."""

    def __init__(self, plan: ComputePlan) -> None:
        self._plan = plan
        self.calls: list[Any] = []

    async def run(self, prompt: Any, **kwargs: Any) -> _MockResult:
        self.calls.append(prompt)
        return _MockResult(output=self._plan)


class _ScriptedToolkit:
    """Returns the next canned observation in order, ignoring inputs."""

    def __init__(self, observations: list[ComputeObservation]) -> None:
        self._obs = list(observations)
        self.dispatched: list[ComputeStep] = []

    async def dispatch(
        self, step: ComputeStep, previous: dict[str, ComputeObservation]
    ) -> ComputeObservation:
        self.dispatched.append(step)
        return self._obs.pop(0)


class TestPatternExecutes:
    async def test_plan_then_execute_each_step(self):
        plan = ComputePlan(
            goal="count Javier's reports",
            steps=[
                SqlRunStep(id="s1", sql="SELECT id FROM employees WHERE name='Javier'", rationale="id"),
                SqlRunStep(
                    id="s2",
                    sql="SELECT name FROM employees WHERE manager_id=:mid",
                    params={"mid": StepRef(step_id="s1", path="$.rows[0].id")},
                    rationale="reports",
                ),
                ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s2", path="$.rows")], rationale="count"),
            ],
        )
        agent = _PlanAgent(plan)
        toolkit = _ScriptedToolkit(
            [
                ComputeObservation(step_id="s1", success=True, output={"rows": [{"id": 1}], "columns": ["id"]}),
                ComputeObservation(
                    step_id="s2",
                    success=True,
                    output={
                        "rows": [{"name": "Ana"}, {"name": "Luis"}, {"name": "Pia"}, {"name": "Tom"}],
                        "columns": ["name"],
                    },
                ),
                ComputeObservation(step_id="a1", success=True, output={"op": "count", "result": 4}),
            ]
        )
        pattern = CorpusComputePattern(toolkit=toolkit, max_steps=10)
        result = await pattern.execute(agent, "How many direct reports does Javier have?")
        assert result.success
        # output is ComputedFacts
        assert isinstance(result.output, ComputedFacts)
        # final scalar exposed in values under the last step's id
        assert result.output.values["a1"] == 4
        # trace contains action+observation pairs for each plan step plus an initial PlanStep
        kinds = [type(s).__name__ for s in result.trace.steps]
        assert kinds.count("ActionStep") == 3
        assert kinds.count("ObservationStep") == 3

    async def test_failed_step_stops_pattern_when_no_replan(self):
        plan = ComputePlan(
            goal="break",
            steps=[
                SqlRunStep(id="s1", sql="DELETE FROM x", rationale="bad"),
                ArithStep(id="a1", op="count", inputs=[], rationale="never reached"),
            ],
        )
        agent = _PlanAgent(plan)
        toolkit = _ScriptedToolkit(
            [
                ComputeObservation(step_id="s1", success=False, error="sql is not read-only"),
            ]
        )
        pattern = CorpusComputePattern(toolkit=toolkit, max_steps=5)
        result = await pattern.execute(agent, "x")
        assert not result.success
        # ArithStep is never dispatched
        assert len(toolkit.dispatched) == 1
        # error surfaces on ComputedFacts via metadata
        assert "read-only" in result.output.values.get("__error__", "")

    async def test_citations_aggregated_from_observations(self):
        plan = ComputePlan(
            goal="x",
            steps=[
                SqlRunStep(id="s1", sql="SELECT 1", rationale="x"),
            ],
        )
        agent = _PlanAgent(plan)
        toolkit = _ScriptedToolkit(
            [
                ComputeObservation(
                    step_id="s1",
                    success=True,
                    output={"rows": [{"x": 1}], "columns": ["x"]},
                    citations=["doc1#0", "doc2#1"],
                )
            ]
        )
        pattern = CorpusComputePattern(toolkit=toolkit, max_steps=2)
        result = await pattern.execute(agent, "x")
        assert set(result.output.citations) == {"doc1#0", "doc2#1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/reasoning/test_corpus_compute.py -v`
Expected: `ModuleNotFoundError: ...corpus_compute`

- [ ] **Step 3: Implement the pattern**

Create `fireflyframework_agentic/reasoning/corpus_compute.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Plan-and-dispatch reasoning pattern for the corpus compute stage.

Generates a :class:`ComputePlan` of typed :class:`ComputeStep` items from
the input question, then executes each step deterministically via a
caller-supplied toolkit.  Only the planner call goes through an LLM; each
step is dispatched to Python code with structured inputs and outputs.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from pydantic_ai.models import Model

from fireflyframework_agentic.exceptions import ReasoningError
from fireflyframework_agentic.prompts.template import PromptTemplate
from fireflyframework_agentic.reasoning.base import AbstractReasoningPattern
from fireflyframework_agentic.reasoning.compute_steps import (
    ComputedFacts,
    ComputeObservation,
    ComputePlan,
    ComputeStep,
)
from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    PlanStep,
    ReasoningStep,
    ThoughtStep,
)

if TYPE_CHECKING:
    from fireflyframework_agentic.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)


class _ToolkitLike(Protocol):
    """Minimal toolkit contract the pattern depends on."""

    async def dispatch(
        self, step: ComputeStep, previous: dict[str, ComputeObservation]
    ) -> ComputeObservation: ...


_PLAN_PROMPT = PromptTemplate(
    system=(
        "You are the planner for a corpus compute stage.\n"
        "Produce a ComputePlan: an ordered list of typed ComputeStep items\n"
        "that, when executed deterministically, will answer the question.\n"
        "Each step must reference prior step outputs via StepRef(step_id, path)\n"
        "instead of repeating values inline.  Do not perform arithmetic in\n"
        "your head.  Prefer SQL for retrieval, arith for numeric ops, join\n"
        "for multi-hop lookups, convert for unit changes, lookup for chunk\n"
        "citation, and verify to cross-check the final value against a source."
    ),
    user="Question: {{ question }}\n\nRetrieval context summary:\n{{ context }}\n",
)


class CorpusComputePattern(AbstractReasoningPattern):
    """Plan a sequence of typed compute steps and dispatch each one."""

    def __init__(
        self,
        *,
        toolkit: _ToolkitLike,
        max_steps: int = 10,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        super().__init__(
            "corpus_compute",
            max_steps=max_steps,
            model=model,
            prompts=prompts,
            reviewer=reviewer,
            step_timeout=step_timeout,
        )
        self._toolkit = toolkit

    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        if "plan" not in state:
            plan = await self._generate_plan(state)
            state["plan"] = plan
            state["plan_index"] = 0
            state["observations"] = {}
            return PlanStep(
                description=f"Generated compute plan with {len(plan.steps)} steps",
                sub_steps=[f"{s.id}: {s.kind} — {s.rationale}" for s in plan.steps],
            )
        idx = state["plan_index"]
        plan: ComputePlan = state["plan"]
        if idx >= len(plan.steps):
            return None
        step = plan.steps[idx]
        return ThoughtStep(content=step.rationale or f"executing {step.kind} step '{step.id}'")

    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        plan: ComputePlan = state["plan"]
        idx = state["plan_index"]
        if idx >= len(plan.steps):
            return None
        step = plan.steps[idx]
        t0 = time.monotonic()
        obs = await self._toolkit.dispatch(step, state["observations"])
        elapsed = time.monotonic() - t0
        state["observations"][step.id] = obs
        state["last_obs"] = obs
        state["plan_index"] = idx + 1
        logger.info("compute step '%s' (%s) %s in %.2fs", step.id, step.kind, "ok" if obs.success else "FAIL", elapsed)
        return ActionStep(tool_name=step.kind, tool_args={"step_id": step.id, "rationale": step.rationale})

    async def _observe(self, state: dict[str, Any], action: ReasoningStep | None) -> ReasoningStep | None:
        obs: ComputeObservation | None = state.get("last_obs")
        if obs is None:
            return None
        content = obs.error if not obs.success else str(obs.output)[:200]
        return ObservationStep(content=content, source=obs.step_id)

    async def _should_continue(self, state: dict[str, Any]) -> bool:
        plan: ComputePlan = state.get("plan")
        if plan is None:
            return True
        last: ComputeObservation | None = state.get("last_obs")
        if last is not None and not last.success:
            return False
        return state["plan_index"] < len(plan.steps)

    async def _extract_output(self, state: dict[str, Any]) -> ComputedFacts:
        observations: dict[str, ComputeObservation] = state.get("observations", {})
        values: dict[str, Any] = {}
        citations: list[str] = []
        for sid, obs in observations.items():
            if obs.success:
                values[sid] = _value_of(obs)
                citations.extend(obs.citations)
        last: ComputeObservation | None = state.get("last_obs")
        if last is not None and not last.success:
            values["__error__"] = last.error or "unknown error"
        return ComputedFacts(values=values, citations=sorted(set(citations)))

    async def _generate_plan(self, state: dict[str, Any]) -> ComputePlan:
        agent = state["agent"]
        template = self._get_prompt("plan", _PLAN_PROMPT)
        context_summary = state.get("context_summary", "")
        prompt = template.render(question=str(state["input"]), context=context_summary)
        try:
            plan = await self._structured_run(agent, prompt, ComputePlan)
        except Exception as exc:
            raise ReasoningError(f"plan generation failed: {exc}") from exc
        return plan

    async def execute(self, agent: Any, input: Any, **kwargs: Any) -> Any:  # noqa: D401 — override
        try:
            return await super().execute(agent, input, **kwargs)
        except ReasoningError:
            # Surface failure as a ReasoningResult with success=False and an
            # error marker on ComputedFacts.  The compute stage is best-effort
            # — the narrator must still get a chance to produce a chunks-only
            # answer.
            from fireflyframework_agentic.reasoning.trace import ReasoningResult, ReasoningTrace

            trace = ReasoningTrace(pattern_name=self._name)
            trace.complete()
            return ReasoningResult(
                output=ComputedFacts(values={"__error__": "compute stage aborted"}, citations=[]),
                trace=trace,
                steps_taken=0,
                success=False,
            )


def _value_of(obs: ComputeObservation) -> Any:
    """Surface the most useful scalar / rowset from an observation's output."""
    if obs.output is None:
        return None
    if isinstance(obs.output, dict):
        if "result" in obs.output:
            return obs.output["result"]
        if "rows" in obs.output:
            return obs.output["rows"]
    return obs.output
```

- [ ] **Step 4: Re-export the pattern from `reasoning/__init__.py`**

Add to `fireflyframework_agentic/reasoning/__init__.py`:

```python
from fireflyframework_agentic.reasoning.corpus_compute import CorpusComputePattern
```

And add `"CorpusComputePattern"` to `__all__` (keep the list alphabetised).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/reasoning/test_corpus_compute.py -v`
Expected: all three tests pass

- [ ] **Step 6: Run the entire reasoning test suite to confirm no regression**

Run: `uv run pytest tests/unit/reasoning -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add fireflyframework_agentic/reasoning/corpus_compute.py \
        fireflyframework_agentic/reasoning/__init__.py \
        tests/unit/reasoning/test_corpus_compute.py
git commit -m "feat(reasoning): CorpusComputePattern with typed step dispatch"
```

---

## Task 6: `CorpusComputeStage` adapter

**Files:**
- Create: `fireflyframework_agentic/rag/retrieval/compute_stage.py`
- Test: extend `tests/unit/corpus_search/test_compute_toolkit.py` with a stage-level smoke test (kept in the same file to keep corpus-search tests co-located)

- [ ] **Step 1: Add failing test for the stage adapter**

Append a new test class to `tests/unit/corpus_search/test_compute_toolkit.py`:

```python
from fireflyframework_agentic.rag.retrieval.compute_stage import CorpusComputeStage
from fireflyframework_agentic.reasoning.compute_steps import ComputedFacts, ComputePlan


class _FakePlannerAgent:
    def __init__(self, plan: ComputePlan) -> None:
        self._plan = plan

    async def run(self, prompt, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(output=self._plan)


class TestCorpusComputeStage:
    async def test_stage_runs_end_to_end_against_real_sqlite(self, employees_db):
        plan = ComputePlan(
            goal="count Javier's reports",
            steps=[
                SqlRunStep(id="s1", sql="SELECT id FROM employees WHERE name='Javier'", rationale="id"),
                SqlRunStep(
                    id="s2",
                    sql="SELECT name FROM employees WHERE manager_id = :mid",
                    params={"mid": StepRef(step_id="s1", path="$.rows[0].id")},
                    rationale="reports",
                ),
                ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s2", path="$.rows")], rationale="count"),
            ],
        )
        stage = CorpusComputeStage(
            corpus_db_path=employees_db,
            planner_agent_factory=lambda: _FakePlannerAgent(plan),
        )
        result = await stage.run(
            question="How many direct reports does Javier have?",
            top_hits=[],
            sql_outcome=None,
            schemas=[],
        )
        assert result.success
        assert isinstance(result.output, ComputedFacts)
        assert result.output.values["a1"] == 4
        # trace contains the three action/observation pairs
        kinds = [type(s).__name__ for s in result.trace.steps]
        assert kinds.count("ActionStep") == 3

    async def test_stage_short_circuits_when_no_signal(self, employees_db):
        stage = CorpusComputeStage(
            corpus_db_path=employees_db,
            planner_agent_factory=lambda: _FakePlannerAgent(ComputePlan(goal="x", steps=[])),
        )
        result = await stage.run(question="x", top_hits=[], sql_outcome=None, schemas=[], skip_if_no_signal=True)
        # With no chunks and no sql_outcome the stage returns an empty ComputedFacts
        assert result.output.values == {}
        assert result.trace.steps == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py::TestCorpusComputeStage -v`
Expected: `ModuleNotFoundError: ...compute_stage`

- [ ] **Step 3: Implement the adapter**

Create `fireflyframework_agentic/rag/retrieval/compute_stage.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Thin adapter that wires CorpusComputePattern + ComputeToolkit together.

Owns the planner agent factory and the per-call toolkit construction so
the rest of the RAG pipeline only depends on the stage's :meth:`run`
contract.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.compute_toolkit import (
    ComputeToolkit,
    RetrievalContext,
)
from fireflyframework_agentic.rag.retrieval.sql import SqlRetrievalOutcome, TargetSchema
from fireflyframework_agentic.reasoning.compute_steps import ComputedFacts
from fireflyframework_agentic.reasoning.corpus_compute import CorpusComputePattern
from fireflyframework_agentic.reasoning.trace import ReasoningResult, ReasoningTrace


class CorpusComputeStage:
    """Glue between corpus retrieval and the generic compute pattern."""

    def __init__(
        self,
        *,
        corpus_db_path: Path,
        planner_agent_factory: Callable[[], Any],
        max_steps: int = 10,
        step_timeout: float | None = 60.0,
        conversion_rates: dict[tuple[str, str], float] | None = None,
    ) -> None:
        self._db_path = corpus_db_path
        self._planner_factory = planner_agent_factory
        self._max_steps = max_steps
        self._step_timeout = step_timeout
        self._conversion_rates = conversion_rates or {}

    async def run(
        self,
        *,
        question: str,
        top_hits: Sequence[ChunkHit],
        sql_outcome: SqlRetrievalOutcome | None,
        schemas: list[TargetSchema],
        skip_if_no_signal: bool = True,
    ) -> ReasoningResult:
        has_signal = bool(top_hits) or (
            sql_outcome is not None and sql_outcome.outcome in ("answered", "empty")
        )
        if skip_if_no_signal and not has_signal:
            return ReasoningResult(
                output=ComputedFacts(),
                trace=ReasoningTrace(pattern_name="corpus_compute"),
                steps_taken=0,
                success=True,
            )

        toolkit = ComputeToolkit(
            corpus_db_path=self._db_path,
            retrieval_context=RetrievalContext(
                top_hits=list(top_hits),
                sql_outcome=sql_outcome,
                schemas=schemas,
            ),
        )
        for (frm, to), rate in self._conversion_rates.items():
            toolkit.set_conversion_rate(frm, to, rate)

        pattern = CorpusComputePattern(
            toolkit=toolkit,
            max_steps=self._max_steps,
            step_timeout=self._step_timeout,
        )
        agent = self._planner_factory()
        context_summary = _summarise_context(top_hits, sql_outcome)
        return await pattern.execute(agent, question, context_summary=context_summary)


def _summarise_context(
    top_hits: Sequence[ChunkHit],
    sql_outcome: SqlRetrievalOutcome | None,
) -> str:
    """One-line-per-source summary for the planner prompt context slot."""
    lines: list[str] = []
    if sql_outcome is not None and sql_outcome.outcome == "answered" and sql_outcome.result_markdown:
        lines.append("Structured data was retrieved as a markdown table:")
        lines.append(sql_outcome.result_markdown)
    for h in top_hits[:5]:
        snippet = h.content[:160].replace("\n", " ")
        lines.append(f"[{h.chunk_id}] {snippet}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/corpus_search/test_compute_toolkit.py::TestCorpusComputeStage -v`
Expected: both stage tests pass

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/compute_stage.py \
        tests/unit/corpus_search/test_compute_toolkit.py
git commit -m "feat(rag): CorpusComputeStage adapter"
```

---

## Task 7: Extend `Answer` model + narrator instructions

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/answerer.py`
- Test: `tests/unit/corpus_search/test_answerer_with_compute.py` (new)

- [ ] **Step 1: Add failing tests for the extended `Answer` and narrator behaviour**

Create `tests/unit/corpus_search/test_answerer_with_compute.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the answerer when a ComputedFacts payload is present."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.reasoning.compute_steps import ComputedFacts


@dataclass
class _Result:
    output: Any


def _hit(cid: str) -> ChunkHit:
    return ChunkHit(chunk_id=cid, score=0.9, content="x", metadata={}, source_path=f"{cid}.pdf")


class TestAnswerExtensions:
    def test_answer_has_optional_trace_and_facts(self):
        a = Answer(text="hello", citations=[], cited_sources=[])
        assert a.computed_facts is None
        assert a.trace is None


class TestNarratorReceivesComputedFacts:
    async def test_prompt_includes_computed_facts_block(self):
        agent = AnswerAgent(model="anthropic:claude-sonnet-4-6")
        facts = ComputedFacts(
            values={"direct_reports_count": 4, "direct_reports": ["Ana", "Luis", "Pia", "Tom"]},
            citations=["org_chart.pdf#p3"],
        )
        captured: dict[str, str] = {}

        async def fake_run(prompt: str, **_: Any) -> _Result:
            captured["prompt"] = prompt
            return _Result(output=Answer(text="Javier has 4 direct reports.", citations=[], cited_sources=[]))

        with patch.object(agent._agent, "run", side_effect=fake_run):
            await agent.answer(
                question="How many reports does Javier have?",
                hits=[_hit("org_chart.pdf#p3")],
                computed=facts,
            )

        prompt = captured["prompt"]
        assert "Computed Facts" in prompt
        assert "direct_reports_count" in prompt
        # narrator instructions must include the no-recomputation rule
        assert "do not perform arithmetic" in agent._agent.instructions.lower()


class TestNarratorShortCircuit:
    async def test_no_hits_no_sql_no_facts_returns_no_info(self):
        agent = AnswerAgent(model="anthropic:claude-sonnet-4-6")
        out = await agent.answer(question="?", hits=[], computed=None)
        assert out.text.startswith("I don't have enough information")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/corpus_search/test_answerer_with_compute.py -v`
Expected: failures referencing `computed_facts`, `trace`, or `do not perform arithmetic` not being present

- [ ] **Step 3: Extend `Answer` and update `AnswerAgent`**

Edit `fireflyframework_agentic/rag/retrieval/answerer.py`:

Add imports near the top:

```python
from fireflyframework_agentic.reasoning.compute_steps import ComputedFacts
from fireflyframework_agentic.reasoning.trace import ReasoningTrace
```

Extend the `_INSTRUCTIONS` constant — append a new rule 5:

```python
5. When a 'Computed Facts' block is present, take any numeric or list \
quantity verbatim from it. Do not perform arithmetic, aggregation, or \
unit conversion in your prose — those values were already computed \
deterministically. If a needed value is missing from Computed Facts, \
say so explicitly rather than recomputing.
```

(Lowercase "do not perform arithmetic" must be present so the test substring match works — keep that exact wording in the rule.)

Add new fields to the `Answer` model:

```python
class Answer(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)
    cited_sources: list[CitedSource] = Field(default_factory=list)
    computed_facts: ComputedFacts | None = None
    trace: ReasoningTrace | None = None
```

Change the `AnswerAgent.answer` signature to accept `computed` and weave it into the prompt:

```python
    async def answer(
        self,
        question: str,
        hits: Sequence[ChunkHit],
        *,
        sql_outcome: SqlRetrievalOutcome | None = None,
        computed: ComputedFacts | None = None,
    ) -> Answer:
        async with timed_span(
            "firefly.rag.answer",
            histogram=query_stage_duration,
            attributes={
                "n_hits": len(hits),
                "model": self._model,
                "has_computed_facts": computed is not None,
            },
            metric_labels={"stage": "answer"},
        ) as span:
            sql_has_signal = sql_outcome is not None and sql_outcome.outcome in ("answered", "empty")
            has_compute_signal = computed is not None and (computed.values or computed.citations)
            if not hits and not sql_has_signal and not has_compute_signal:
                span.set_attribute("firefly.rag.short_circuit", "no_hits_no_sql_no_compute")
                return Answer(text=_NO_INFO_TEXT, citations=[], cited_sources=[])
            parts: list[str] = [f"Question: {question}"]
            if computed is not None and (computed.values or computed.citations):
                parts.append(_format_computed_facts_section(computed))
            if sql_outcome is not None and sql_outcome.outcome == "answered":
                parts.append(f"## Structured Data Results\n\n{sql_outcome.result_markdown}")
            elif sql_outcome is not None and sql_outcome.outcome == "empty":
                parts.append(_format_empty_sql_section(sql_outcome))
            formatted = format_chunks_for_prompt(hits)
            if formatted:
                parts.append(f"## Retrieved Documents\n\n{formatted}")
            prompt = "\n\n".join(parts)
            result = await self._agent.run(prompt)
            answer = result.output
            answer.cited_sources = _build_cited_sources(answer.citations, hits)
            answer.computed_facts = computed
            span.set_attribute("firefly.rag.citation_count", len(answer.cited_sources))
            span.set_attribute(
                "firefly.rag.hallucinated_citation_count",
                max(0, len(answer.citations) - len(answer.cited_sources)),
            )
            return answer
```

Add the new section formatter at module level near `_format_empty_sql_section`:

```python
def _format_computed_facts_section(facts: ComputedFacts) -> str:
    """Render computed values + their citations as a labelled prompt block."""
    lines = ["## Computed Facts"]
    for k, v in facts.values.items():
        lines.append(f"- {k}: {v}")
    if facts.citations:
        lines.append("")
        lines.append(f"Sources: {', '.join(facts.citations)}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/corpus_search/test_answerer_with_compute.py tests/unit/corpus_search/test_answerer_sql_context.py -v`
Expected: all tests pass (the existing `test_answerer_sql_context.py` is unaffected; the new tests pass)

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/answerer.py \
        tests/unit/corpus_search/test_answerer_with_compute.py
git commit -m "feat(rag): narrator accepts ComputedFacts and forbids recomputation"
```

---

## Task 8: Wire `compute_stage` into `CorpusAgent.query` (flag-gated)

**Files:**
- Modify: `fireflyframework_agentic/rag/agent.py`
- Test: `tests/unit/corpus_search/test_agent_query.py` (extend existing)

- [ ] **Step 1: Read the relevant section to confirm exact line numbers before editing**

Run: `uv run python -c "import inspect; from fireflyframework_agentic.rag import agent; print(inspect.getsourcefile(agent))"`
Expected: prints the path to `agent.py`. Use this to confirm the edit target if line numbers have drifted.

- [ ] **Step 2: Add a failing test for the flag-gated wiring**

Append to `tests/unit/corpus_search/test_agent_query.py` (or create the file if it doesn't have a comparable shape — adapt the imports):

```python
import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputedFacts,
    ComputePlan,
    SqlRunStep,
    StepRef,
)


class _FakePlanner:
    def __init__(self, plan: ComputePlan) -> None:
        self._plan = plan

    async def run(self, prompt, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(output=self._plan)


class TestComputeStageFlag:
    async def test_flag_off_keeps_existing_behaviour(self, tmp_path, monkeypatch):
        # A fresh corpus with the structured-only path disabled (no schemas)
        # behaves exactly as before when enable_compute_stage=False.
        agent = CorpusAgent(root=tmp_path, enable_compute_stage=False)
        # Use the existing test harness to ingest a tiny doc then query.
        # (The shape of this block mirrors the pre-existing test in the file —
        #  use whichever ingest helper the file already uses.)
        ...

    async def test_flag_on_attaches_trace_and_facts(self, tmp_path, monkeypatch):
        plan = ComputePlan(
            goal="count",
            steps=[
                SqlRunStep(id="s1", sql="SELECT 1 AS x", rationale="smoke"),
                ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s1", path="$.rows")], rationale="count rows"),
            ],
        )
        agent = CorpusAgent(
            root=tmp_path,
            enable_compute_stage=True,
            compute_planner_factory=lambda: _FakePlanner(plan),
        )
        # ingest minimal content so retrieval returns something
        ...
        answer = await agent.query("smoke test")
        assert answer.trace is not None
        assert answer.computed_facts is not None
        assert "a1" in answer.computed_facts.values
```

(Note: the existing `test_agent_query.py` has its own ingest helper — keep parity with its pattern. The two `...` placeholders above are intentionally short because we are following an existing file's idioms; copy from a neighbouring test in the same file rather than inventing new harness code.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/corpus_search/test_agent_query.py::TestComputeStageFlag -v`
Expected: failures — `CorpusAgent` does not accept `enable_compute_stage` or `compute_planner_factory`.

- [ ] **Step 4: Add the constructor args and wire the stage**

Edit `fireflyframework_agentic/rag/agent.py`:

Near the existing imports, add:

```python
from fireflyframework_agentic.rag.retrieval.compute_stage import CorpusComputeStage
```

Locate `__init__` (around the area where `self._answerer: AnswerAgent | None = None` is initialised, ~line 235). Add the new optional args to the constructor signature and store them:

```python
        enable_compute_stage: bool = True,
        compute_planner_factory: Callable[[], Any] | None = None,
        compute_conversion_rates: dict[tuple[str, str], float] | None = None,
```

Inside `__init__`, near where `self._answerer = ...` would be initialised:

```python
        self._enable_compute_stage = enable_compute_stage
        self._compute_planner_factory = compute_planner_factory
        self._compute_conversion_rates = compute_conversion_rates or {}
        self._compute_stage: CorpusComputeStage | None = None
```

Where the existing `_ensure_query_ready` builds `self._answerer`, add an analogous block:

```python
        if self._enable_compute_stage and self._compute_stage is None:
            self._compute_stage = CorpusComputeStage(
                corpus_db_path=self.root / "corpus.sqlite",
                planner_agent_factory=self._compute_planner_factory or self._default_compute_planner_factory,
                conversion_rates=self._compute_conversion_rates,
            )
```

Add a tiny default factory next to that method:

```python
    def _default_compute_planner_factory(self):
        # Default to the same Haiku-tier model used by the SQL retriever — the
        # planner only chooses steps and their arguments; it does not narrate.
        return FireflyAgent(
            name="corpus_compute_planner",
            model=self._sql_model,
            output_type=ComputePlan,
            instructions=(
                "You produce a ComputePlan for the corpus compute stage. "
                "Refer to prior step outputs via StepRef; do not perform any "
                "arithmetic yourself."
            ),
        )
```

Make sure `ComputePlan` is imported at the top of `agent.py`:

```python
from fireflyframework_agentic.reasoning.compute_steps import ComputePlan
```

In `query()` (around `rag/agent.py:636-640`), insert the compute call between retrieval and the answerer:

```python
            top_hits, sql_outcome = await asyncio.gather(
                self.retrieve(question, top_k=top_k, rerank=True),
                self._structured_retriever.retrieve(question, schemas),
            )
            compute_result = None
            if self._compute_stage is not None:
                compute_result = await self._compute_stage.run(
                    question=question,
                    top_hits=top_hits,
                    sql_outcome=sql_outcome,
                    schemas=schemas,
                )
            computed = compute_result.output if compute_result is not None else None
            answer = await self._answerer.answer(
                question,
                top_hits,
                sql_outcome=sql_outcome,
                computed=computed,
            )
            if compute_result is not None:
                answer.trace = compute_result.trace
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/corpus_search/test_agent_query.py -v`
Expected: all tests pass — both the new `TestComputeStageFlag` block and the pre-existing tests in the file.

- [ ] **Step 6: Run the whole corpus_search suite to catch any regressions**

Run: `uv run pytest tests/unit/corpus_search -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add fireflyframework_agentic/rag/agent.py \
        tests/unit/corpus_search/test_agent_query.py
git commit -m "feat(rag): wire CorpusComputeStage into CorpusAgent.query (default on)"
```

---

## Task 9: Integration tests for the three failure scenarios

**Files:**
- Create: `tests/integration/test_corpus_agent_compute.py`

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_corpus_agent_compute.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""End-to-end CorpusAgent.query() tests for the three compute failure classes.

The planner LLM and the narrator LLM are both mocked so the tests are
deterministic, but every other component (SQLite, retrieval, toolkit) is
real.  CLAUDE.md forbids mocking the database in integration tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.rag.retrieval.answerer import Answer
from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputePlan,
    ConvertStep,
    JoinStep,
    SqlRunStep,
    StepRef,
)


@dataclass
class _Result:
    output: Any


class _ScriptedAgent:
    def __init__(self, output: Any) -> None:
        self._output = output

    async def run(self, prompt: Any, **kwargs: Any) -> _Result:
        return _Result(output=self._output)


@pytest.fixture
def orgchart_corpus(tmp_path: Path) -> CorpusAgent:
    # Use the existing CorpusAgent ingest path the project already has tests
    # for — see tests/integration/test_corpus_agent_structured.py for the
    # canonical setup.  Build a minimal employees table + a tiny org_chart
    # chunk so retrieval has both structured and unstructured signal.
    agent = CorpusAgent(
        root=tmp_path,
        enable_compute_stage=True,
        compute_planner_factory=None,  # set per-test
    )
    # ingestion details follow the existing helper; intentionally short here
    return agent


class TestDirectReportsScenario:
    async def test_two_hop_join_with_count(self, orgchart_corpus, monkeypatch):
        plan = ComputePlan(
            goal="direct reports of Javier",
            steps=[
                SqlRunStep(id="s1", sql="SELECT id FROM employees WHERE name='Javier'", rationale="id"),
                SqlRunStep(
                    id="s2",
                    sql="SELECT name FROM employees WHERE manager_id=:mid",
                    params={"mid": StepRef(step_id="s1", path="$.rows[0].id")},
                    rationale="reports",
                ),
                ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s2", path="$.rows")], rationale="count"),
            ],
        )
        # Override factory + narrator
        orgchart_corpus._compute_planner_factory = lambda: _ScriptedAgent(plan)  # noqa: SLF001
        monkeypatch.setattr(
            orgchart_corpus,
            "_default_compute_planner_factory",
            lambda: _ScriptedAgent(plan),
        )

        answer = await orgchart_corpus.query("Who are the direct reports of Javier?")
        assert answer.computed_facts is not None
        assert answer.computed_facts.values["a1"] == 4
        assert answer.trace is not None
        kinds = [type(s).__name__ for s in answer.trace.steps]
        assert kinds.count("ActionStep") == 3


class TestArithmeticScenario:
    async def test_gross_margin_percent(self, orgchart_corpus, monkeypatch):
        plan = ComputePlan(
            goal="gross margin",
            steps=[
                SqlRunStep(
                    id="s1",
                    sql="SELECT value FROM finance_fact WHERE metric_line='Revenue'",
                    rationale="revenue",
                ),
                SqlRunStep(
                    id="s2",
                    sql="SELECT value FROM finance_fact WHERE metric_line='COGS'",
                    rationale="cogs",
                ),
                ArithStep(
                    id="a1",
                    op="diff",
                    inputs=[
                        StepRef(step_id="s1", path="$.rows[0].value"),
                        StepRef(step_id="s2", path="$.rows[0].value"),
                    ],
                    rationale="gross profit",
                ),
                ArithStep(
                    id="a2",
                    op="percent",
                    inputs=[StepRef(step_id="a1", path="$.result"), StepRef(step_id="s1", path="$.rows[0].value")],
                    rationale="margin",
                ),
            ],
        )
        orgchart_corpus._compute_planner_factory = lambda: _ScriptedAgent(plan)  # noqa: SLF001
        # ingestion of finance_fact omitted for brevity; mirror test_corpus_agent_structured.py
        answer = await orgchart_corpus.query("What is the gross margin?")
        assert "a2" in answer.computed_facts.values


class TestConversionScenario:
    async def test_revenue_in_eur(self, orgchart_corpus, monkeypatch):
        plan = ComputePlan(
            goal="revenue in EUR",
            steps=[
                SqlRunStep(
                    id="s1",
                    sql="SELECT value FROM finance_fact WHERE metric_line='Revenue'",
                    rationale="usd",
                ),
                ConvertStep(
                    id="c1",
                    value=StepRef(step_id="s1", path="$.rows[0].value"),
                    from_unit="USD",
                    to_unit="EUR",
                    rationale="convert",
                ),
            ],
        )
        orgchart_corpus._compute_planner_factory = lambda: _ScriptedAgent(plan)  # noqa: SLF001
        orgchart_corpus._compute_conversion_rates = {("USD", "EUR"): 0.9}  # noqa: SLF001
        answer = await orgchart_corpus.query("What was the revenue in EUR?")
        assert "c1" in answer.computed_facts.values
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/integration/test_corpus_agent_compute.py -v`
Expected: tests pass. (The ingestion harness lines marked "follows the existing helper" / "mirror test_corpus_agent_structured.py" mean: copy the exact ingest call sequence from the neighbouring integration test — do not invent a new harness.)

- [ ] **Step 3: Run the integration suite to catch regressions**

Run: `uv run pytest tests/integration -v`
Expected: every previously-passing test still passes; the new file is green.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_corpus_agent_compute.py
git commit -m "test(rag): integration tests for compute stage failure scenarios"
```

---

## Task 10: Telemetry spans

**Files:**
- Modify: `fireflyframework_agentic/rag/_telemetry.py`
- Modify: `fireflyframework_agentic/reasoning/corpus_compute.py` (emit spans)
- Test: extend `tests/observability/` with a span-emission test

- [ ] **Step 1: Find the existing span helper and a representative test**

Run: `grep -rn "timed_span" /Users/javi/work/fireflyframework-agentic/fireflyframework_agentic/rag/_telemetry.py`
Expected: confirms the helper signature; copy it for the new span name.

Run: `ls /Users/javi/work/fireflyframework-agentic/tests/observability/`
Expected: identifies the right file pattern to follow.

- [ ] **Step 2: Add a failing test for the compute span**

Create or extend a test file under `tests/observability/test_compute_spans.py` (use the existing observability test idioms):

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Telemetry: a CorpusComputePattern run emits a parent span + per-step children."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.reasoning.compute_steps import (
    ArithStep,
    ComputePlan,
    ComputeObservation,
    SqlRunStep,
    StepRef,
)
from fireflyframework_agentic.reasoning.corpus_compute import CorpusComputePattern


@pytest.fixture
def span_recorder():
    # Use the project's existing OTel test fixture pattern; if there is a
    # shared conftest.py with an in-memory exporter, reuse it.
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


class _PlanAgent:
    def __init__(self, plan):
        self._plan = plan

    async def run(self, prompt, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(output=self._plan)


class _Toolkit:
    async def dispatch(self, step, previous):
        return ComputeObservation(step_id=step.id, success=True, output={"result": 1})


async def test_compute_span_emitted_with_per_step_children(span_recorder):
    plan = ComputePlan(
        goal="x",
        steps=[
            SqlRunStep(id="s1", sql="SELECT 1", rationale="x"),
            ArithStep(id="a1", op="count", inputs=[StepRef(step_id="s1", path="$.rows")], rationale="x"),
        ],
    )
    pattern = CorpusComputePattern(toolkit=_Toolkit(), max_steps=5)
    await pattern.execute(_PlanAgent(plan), "x")

    spans = span_recorder.get_finished_spans()
    names = [s.name for s in spans]
    assert "firefly.rag.compute" in names
    assert names.count("firefly.rag.compute.step") == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/observability/test_compute_spans.py -v`
Expected: the span names are absent — `assert` fails.

- [ ] **Step 4: Emit spans in the pattern**

Edit `fireflyframework_agentic/reasoning/corpus_compute.py`:

Import the telemetry helper at the top:

```python
from fireflyframework_agentic.rag._telemetry import timed_span
```

Wrap `execute` body in a `timed_span` (open the parent span around the `super().execute(...)` call):

```python
    async def execute(self, agent: Any, input: Any, **kwargs: Any) -> Any:
        async with timed_span(
            "firefly.rag.compute",
            attributes={"max_steps": self._max_steps},
        ) as span:
            try:
                result = await super().execute(agent, input, **kwargs)
                span.set_attribute("compute.outcome", "succeeded" if result.success else "failed")
                span.set_attribute("compute.n_steps", result.steps_taken)
                return result
            except ReasoningError:
                span.set_attribute("compute.outcome", "failed")
                # Falls through to the existing ReasoningResult fallback
                ...  # (keep the existing fallback below)
```

And wrap `_act` per-step dispatch:

```python
    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        plan: ComputePlan = state["plan"]
        idx = state["plan_index"]
        if idx >= len(plan.steps):
            return None
        step = plan.steps[idx]
        async with timed_span(
            "firefly.rag.compute.step",
            attributes={"step.kind": step.kind, "step.id": step.id},
        ) as span:
            obs = await self._toolkit.dispatch(step, state["observations"])
            span.set_attribute("step.success", obs.success)
            if obs.error:
                span.set_attribute("step.error", obs.error[:200])
            state["observations"][step.id] = obs
            state["last_obs"] = obs
            state["plan_index"] = idx + 1
            return ActionStep(tool_name=step.kind, tool_args={"step_id": step.id, "rationale": step.rationale})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/observability/test_compute_spans.py tests/unit/reasoning/test_corpus_compute.py -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add fireflyframework_agentic/reasoning/corpus_compute.py \
        tests/observability/test_compute_spans.py
git commit -m "feat(observability): emit compute span + per-step children"
```

---

## Task 11: MCP / CLI surfacing of `trace` and `computed_facts`

**Files:**
- Modify: `fireflyframework_agentic/tools/builtins/corpus_rag.py`
- Test: locate the existing corpus MCP test (`tests/tools/...` or `tests/integration/test_mcp_corpus_*.py`) and extend it

- [ ] **Step 1: Find the MCP tool definition**

Run: `grep -n "def corpus_query\|corpus_rag" /Users/javi/work/fireflyframework-agentic/fireflyframework_agentic/tools/builtins/corpus_rag.py`
Expected: prints the entry-point lines; read them to confirm the output shape.

- [ ] **Step 2: Add a failing test that asserts the MCP response carries the trace**

Add a test alongside the existing MCP corpus tests (file name should follow the same convention used in the repo, e.g. `tests/integration/test_mcp_corpus_compute.py`). The test should:

- Stand up the MCP server fixture used by `test_mcp_corpus_e2e.py`.
- Call `corpus_query` with a question the planner has been stubbed to handle.
- Assert the JSON response includes a `trace` and `computed_facts` block whose shape matches `ReasoningTrace.model_dump()` and `ComputedFacts.model_dump()`.

(Use the exact shape and harness from a neighbouring file — do not invent.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_mcp_corpus_compute.py -v`
Expected: the response does not yet expose the new fields.

- [ ] **Step 4: Update the MCP tool to surface the new fields**

Edit `fireflyframework_agentic/tools/builtins/corpus_rag.py`:

In the function that constructs the response payload from the `Answer`, add (additive, optional):

```python
response = {
    "text": answer.text,
    "citations": answer.citations,
    "cited_sources": [s.model_dump() for s in answer.cited_sources],
}
if answer.computed_facts is not None and (
    answer.computed_facts.values or answer.computed_facts.citations
):
    response["computed_facts"] = answer.computed_facts.model_dump()
if answer.trace is not None and answer.trace.steps:
    response["trace"] = answer.trace.model_dump()
return response
```

(The existing function may already do something close to this; preserve all current keys and only add the two new conditional blocks.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_mcp_corpus_compute.py tests/integration/test_mcp_corpus_e2e.py -v`
Expected: all tests pass; pre-existing MCP behaviour is unchanged for callers that ignore the new fields.

- [ ] **Step 6: Commit**

```bash
git add fireflyframework_agentic/tools/builtins/corpus_rag.py \
        tests/integration/test_mcp_corpus_compute.py
git commit -m "feat(mcp): surface compute trace and facts in corpus_query response"
```

---

## Task 12: Final full-suite verification + PR

**Files:** none (verification + git operations)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: 100% green.

- [ ] **Step 2: Run linters / type-checkers the project uses**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean. If there are configured pre-commit hooks (mypy, basedpyright), run them too — `pre-commit run --all-files` if `.pre-commit-config.yaml` exists.

- [ ] **Step 3: Manual smoke test the CLI end-to-end**

Run (in a scratch directory): `uv run ff corpus ingest <small-folder> && uv run ff corpus query "a question that exercises a sum"`
Expected: the answer prints; if the project has a `--show-trace` flag (or equivalent), the steps trail prints below the prose answer.

- [ ] **Step 4: Push the branch and open the PR**

```bash
git push -u origin feat/corpus-compute-stage
gh pr create --title "feat(rag): deterministic compute stage with traceable steps" --body "$(cat <<'EOF'
## Summary
- Adds a generic CorpusComputePattern in `reasoning/` that plans a sequence of typed compute steps and dispatches each one to a deterministic Python executor.
- Adds a corpus-bound ComputeToolkit + CorpusComputeStage adapter that runs SQL, arithmetic, joins, conversions, lookups, and verification against the corpus SQLite.
- Wires the stage into `CorpusAgent.query()` between retrieval and the narrator. The narrator's `Answer` now carries `computed_facts` and a `ReasoningTrace` so callers can render a 'how this was computed' trail.

## Test plan
- [x] `uv run pytest -q`
- [x] `uv run pytest tests/integration/test_corpus_agent_compute.py -v` (three failure-class scenarios)
- [x] Manual CLI smoke test against a small fixture corpus

Design: docs/superpowers/specs/2026-05-14-corpus-compute-stage-design.md
Plan: docs/superpowers/plans/2026-05-14-corpus-compute-stage.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Watch CI**

Run: `gh pr checks` (replace with `gh pr checks <N>` if you need a specific PR number)
Expected: all green, including CodeQL / security scans (CLAUDE.md guardrail).

- [ ] **Step 6: Iterate on review feedback**

If CI surfaces anything, fix in a new commit on the same branch. Do not amend; do not `--no-verify`. Do not push directly to main.
