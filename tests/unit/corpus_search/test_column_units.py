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

"""Tests for the optional ``ColumnSpec.unit`` field and the wiring that
carries it from schema definition to the SQL retriever's system prompt
and the answerer's instructions.

Issue #158: when a numeric column is stored without an explicit unit on
the schema, the agent silently returned bare numbers. The fix adds an
optional ``unit`` field and threads it through (a) the schema context
the SQL retriever shows its LLM, (b) the rule in the SQL retriever's
system prompt that tells it to keep the unit in the result, and (c) the
answerer instruction that tells the model to either quote the unit or
flag the ambiguity. The tests below lock in each leg of that wiring
against accidental deletion.

Fixtures use synthetic finance-style data; no values are taken from any
real corpus.
"""

from __future__ import annotations

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.answerer import _INSTRUCTIONS as ANSWERER_INSTRUCTIONS
from fireflyframework_agentic.rag.retrieval.sql import _SYSTEM as SQL_SYSTEM_PROMPT
from fireflyframework_agentic.rag.retrieval.sql import _build_schema_context


def _schema_with_units() -> TargetSchema:
    """Synthetic finance fact table mixing unit-carrying and unit-less columns."""
    return TargetSchema(
        tables=[
            TableSpec(
                name="finance_fact",
                columns=[
                    ColumnSpec(name="year", type=ColumnType.string),
                    ColumnSpec(name="market", type=ColumnType.string),
                    ColumnSpec(name="metric_line", type=ColumnType.string),
                    ColumnSpec(name="revenue", type=ColumnType.float_, unit="USD millions"),
                    ColumnSpec(name="headcount", type=ColumnType.integer, unit="headcount"),
                    ColumnSpec(name="ratio_pct", type=ColumnType.float_, unit="percent"),
                    # Intentionally unit-less to exercise the fallback path.
                    ColumnSpec(name="raw_value", type=ColumnType.float_),
                ],
            )
        ]
    )


def test_columnspec_unit_defaults_to_none():
    """The new field is optional and absent by default — adding it must
    not break callers that omit it (every existing schema in the codebase)."""
    col = ColumnSpec(name="x", type=ColumnType.float_)
    assert col.unit is None


def test_columnspec_unit_accepts_free_form_string():
    """Free-form string by design — covers 'USD millions', 'percent',
    'headcount', 'days', etc. without enforcing an enum the framework
    doesn't own."""
    col = ColumnSpec(name="x", type=ColumnType.float_, unit="USD millions")
    assert col.unit == "USD millions"


def test_schema_context_renders_unit_when_set():
    """Unit metadata must reach the SQL retriever's prompt. The format is
    ``name (type, unit=…)``; we pin the literal so a refactor that
    silently changes the shape regresses an observable agent behaviour."""
    ctx = _build_schema_context([_schema_with_units()])
    assert "revenue (float, unit=USD millions)" in ctx
    assert "headcount (integer, unit=headcount)" in ctx
    assert "ratio_pct (float, unit=percent)" in ctx


def test_schema_context_omits_unit_marker_for_unitless_columns():
    """Backwards compatibility: columns without a unit render unchanged.

    The unit-less column ``raw_value`` should not gain a trailing
    ``unit=…`` clause and the unmodified string-typed columns should not
    sprout one either. Asserting the negative is what catches a bug
    where the formatter unconditionally emits ``unit=None``.
    """
    ctx = _build_schema_context([_schema_with_units()])
    assert "raw_value (float)" in ctx
    assert "raw_value (float, unit=" not in ctx
    assert "year (string)" in ctx
    assert "unit=None" not in ctx


def test_sql_system_prompt_pins_unit_preservation_rule():
    """The SQL retriever's system prompt must instruct the agent to
    preserve units in SELECT results when the schema declares them.

    We assert on a small set of fragments that together describe the
    rule (the ``unit=`` schema marker, the alias example, and the
    "do not silently strip" injunction). Pinning the literal full
    paragraph would be over-rigid — pinning the substantive fragments
    catches accidental removal while leaving room for wording tweaks.
    """
    lowered = SQL_SYSTEM_PROMPT.lower()
    assert "unit=" in SQL_SYSTEM_PROMPT
    assert "alias" in lowered
    assert "do not silently strip the unit" in lowered


def test_answerer_instructions_pin_unit_inclusion_rule():
    """The answerer must include the unit whenever it cites a numeric
    quantity and known, and flag the ambiguity when it isn't.

    Both branches of the rule (known → include; unknown → flag) need to
    be present; pinning both prevents a partial-deletion regression.
    """
    lowered = ANSWERER_INSTRUCTIONS.lower()
    # Known-unit branch:
    assert "include its unit if it is known" in lowered
    # Ambiguous-unit branch:
    assert "flag the ambiguity" in lowered
    # Anti-pattern explicitly called out:
    assert "unit-less number" in lowered
