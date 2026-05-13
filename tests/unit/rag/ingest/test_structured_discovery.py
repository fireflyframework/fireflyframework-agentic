from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.ingest.structured_registry import (
    _SKILL,
    TABULAR_SUFFIXES,
    _csv_sample,
    _sample_for,
    discover_schema,
    discover_schema_for_paths,
    discover_schema_interactive,
    is_tabular_file,
)
from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    SchemaFeedback,
    TableSpec,
    TargetSchema,
)


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "sales.csv"
    p.write_text("id,amount,date\n1,9.99,2026-01-01\n2,19.99,2026-01-02\n")
    return p


@pytest.mark.asyncio
async def test_discover_schema_csv(csv_file: Path):
    expected = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="amount", type=ColumnType.float_),
                    ColumnSpec(name="date", type=ColumnType.date),
                ],
            )
        ]
    )
    mock_result = MagicMock()
    mock_result.output = expected

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        result = await discover_schema(csv_file)

    assert result.tables[0].name == "sales"
    assert len(result.tables[0].columns) == 3


@pytest.mark.asyncio
async def test_discover_schema_passes_sample_to_agent(csv_file: Path):
    mock_result = MagicMock()
    mock_result.output = TargetSchema(
        tables=[TableSpec(name="sales", columns=[ColumnSpec(name="id", type=ColumnType.integer)])]
    )

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        await discover_schema(csv_file)

    prompt = mock_agent.run.call_args[0][0]
    assert "sales.csv" in prompt
    assert "id" in prompt
    assert "amount" in prompt


def _stub_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="data",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_interactive_returns_immediately_when_approved(tmp_path: Path):
    """on_review returning approved=True on first call ends the loop after one round."""
    csv = tmp_path / "data.csv"
    csv.write_text("id\n1\n2\n")

    on_review = AsyncMock(return_value=SchemaFeedback(approved=True))

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(return_value=_stub_schema()),
    ):
        result = await discover_schema_interactive(csv, on_review=on_review)

    assert result == _stub_schema()
    on_review.assert_awaited_once()


@pytest.mark.asyncio
async def test_interactive_refines_on_rejection(tmp_path: Path):
    """on_review returning approved=False triggers a second inference round."""
    csv = tmp_path / "data.csv"
    csv.write_text("id,name\n1,Alice\n")

    schema_v1 = _stub_schema()
    schema_v2 = TargetSchema(
        tables=[
            TableSpec(
                name="t",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer),
                    ColumnSpec(name="name", type=ColumnType.string),
                ],
            )
        ]
    )

    on_review = AsyncMock(
        side_effect=[
            SchemaFeedback(approved=False, corrections="name column is missing"),
            SchemaFeedback(approved=True),
        ]
    )

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(side_effect=[schema_v1, schema_v2]),
    ):
        result = await discover_schema_interactive(csv, on_review=on_review, max_rounds=3)

    assert result == schema_v2
    assert on_review.await_count == 2


@pytest.mark.asyncio
async def test_discover_schema_for_paths_runs_per_file_and_merges(tmp_path: Path):
    """Multi-file discovery is now per-file: one LLM call per CSV/XLSX,
    merged into a single TargetSchema. The previous design (one combined
    LLM call across every sheet of every file) was fragile — a single
    messy sheet anywhere in the combined sample made the model return
    ``{}`` for the entire output. Per-file isolates the failure mode.

    Cross-file foreign keys are no longer auto-proposed on initial
    discovery (the per-file calls can't see each other); the user adds
    them through a refinement round.
    """
    a = tmp_path / "customers.csv"
    a.write_text("id,name\n1,Alice\n")
    b = tmp_path / "orders.csv"
    b.write_text("id,customer_id,total\n1,1,9.99\n")

    customers_schema = TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            )
        ]
    )
    orders_schema = TargetSchema(
        tables=[
            TableSpec(
                name="orders",
                columns=[
                    ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
                    ColumnSpec(name="customer_id", type=ColumnType.integer),
                ],
            )
        ]
    )
    per_file = {"customers.csv": customers_schema, "orders.csv": orders_schema}

    async def fake_discover(path: Path, **kwargs: object) -> TargetSchema:
        return per_file[path.name]

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(side_effect=fake_discover),
    ) as mock_single:
        result = await discover_schema_for_paths([a, b])

    assert mock_single.await_count == 2
    table_names = {t.name for t in result.tables}
    assert table_names == {"customers", "orders"}


@pytest.mark.asyncio
async def test_discover_schema_for_paths_single_path_delegates(tmp_path: Path):
    """A single-file folder collapses to discover_schema (no multi-file prompt)."""
    p = tmp_path / "only.csv"
    p.write_text("id\n1\n")

    expected = TargetSchema(tables=[TableSpec(name="only", columns=[ColumnSpec(name="id", type=ColumnType.integer)])])
    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(return_value=expected),
    ) as mock_single:
        result = await discover_schema_for_paths([p])

    mock_single.assert_awaited_once()
    assert result == expected


@pytest.mark.asyncio
async def test_discover_schema_for_paths_with_corrections(tmp_path: Path):
    """Refinement on a multi-file folder echoes corrections + previous_schema."""
    a = tmp_path / "x.csv"
    a.write_text("id\n1\n")
    b = tmp_path / "y.csv"
    b.write_text("id\n2\n")
    prior = TargetSchema(
        tables=[
            TableSpec(name="x", columns=[ColumnSpec(name="id", type=ColumnType.integer)]),
            TableSpec(name="y", columns=[ColumnSpec(name="id", type=ColumnType.integer)]),
        ]
    )
    expected = TargetSchema(
        tables=[
            TableSpec(
                name="x",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            ),
            TableSpec(
                name="y",
                columns=[ColumnSpec(name="id", type=ColumnType.integer, primary_key=True)],
            ),
        ]
    )
    mock_result = MagicMock()
    mock_result.output = expected

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        await discover_schema_for_paths(
            [a, b],
            corrections="mark id as primary_key on every table",
            previous_schema=prior,
        )

    prompt = mock_agent.run.call_args[0][0]
    assert "User corrections" in prompt
    assert "mark id as primary_key" in prompt
    assert "Previous schema attempt" in prompt


def test_tabular_suffixes_contents() -> None:
    assert frozenset({".csv", ".xls", ".xlsx"}) == TABULAR_SUFFIXES


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.csv", True),
        ("a.CSV", True),
        ("a.xlsx", True),
        ("a.xls", True),
        ("a.pptx", False),
        ("a.pdf", False),
        ("a.docx", False),
        ("noext", False),
    ],
)
def test_is_tabular_file(tmp_path: Path, name: str, expected: bool) -> None:
    assert is_tabular_file(tmp_path / name) is expected


def test_sample_for_raises_on_unsupported_suffix(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"PK\x03\x04binary-zip-bytes")
    with pytest.raises(ValueError, match="unsupported file type"):
        _sample_for(pptx)


def test_csv_sample_wraps_decoding_error_with_hint(tmp_path: Path) -> None:
    """A Latin-1 CSV (Windows export) should fail with a hint, not a raw UnicodeDecodeError."""
    p = tmp_path / "sales.csv"
    # \xba is the masculine ordinal in Latin-1 / CP1252 — invalid in UTF-8.
    p.write_bytes(b"id,producto\n1,Caf\xbae\n")
    with pytest.raises(ValueError, match="UTF-8|Latin-1|CP1252"):
        _csv_sample(p)


@pytest.mark.asyncio
async def test_interactive_returns_last_schema_after_max_rounds(tmp_path: Path):
    """After max_rounds the last schema is returned even without approval."""
    csv = tmp_path / "data.csv"
    csv.write_text("id\n1\n")

    on_review = AsyncMock(return_value=SchemaFeedback(approved=False, corrections="still wrong"))

    with patch(
        "fireflyframework_agentic.rag.ingest.structured_registry.discover_schema",
        new=AsyncMock(return_value=_stub_schema()),
    ):
        result = await discover_schema_interactive(csv, on_review=on_review, max_rounds=2)

    assert result == _stub_schema()
    assert on_review.await_count == 2


# ---- Unit inference in the discovery prompt -----------------------------
#
# PR #165 added the ``unit`` field on ``ColumnSpec`` and wired the SQL
# retriever / answerer to surface and quote it. The schema-discovery
# prompt was NOT updated in that PR, so the discovery LLM never
# populated ``unit`` — every column came back with ``unit=None``,
# defeating the feature for any user who relies on auto-discovery.
# These tests pin the prompt contract so the unit-inference block
# can't get silently removed.


def test_skill_prompt_teaches_unit_inference() -> None:
    """The discovery prompt must instruct the LLM when and how to set
    ``unit`` on numeric columns. Without this, ``ColumnSpec.unit``
    stays ``None`` forever and the answerer's currency / unit
    handling has nothing to surface.
    """
    assert "Unit inference" in _SKILL, (
        "schema-discovery prompt is missing unit-inference guidance — see #170 / PR #171 for context"
    )
    # Spot-check the load-bearing signals so a future edit can't strip
    # them down to a vague one-liner without the test catching it.
    expected_signals = [
        "Parenthesised hint",
        "Currency",
        "percent",
        "headcount",
        "Leave ``unit`` null",
    ]
    missing = [s for s in expected_signals if s not in _SKILL]
    assert not missing, f"unit-inference prompt lost signals: {missing}"


def test_skill_prompt_forbids_unit_on_non_numeric_columns() -> None:
    """The prompt must explicitly tell the LLM NOT to set ``unit`` on
    columns that aren't quantities (strings, dates, primary keys, …).
    The framework otherwise has no way to validate this — pydantic
    happily accepts ``unit="USD"`` on a string column.
    """
    assert "Do NOT set ``unit`` on string" in _SKILL


def test_make_discovery_agent_uses_skill_as_full_instructions() -> None:
    """Confirm the discovery agent's instructions are ``_SKILL`` itself,
    not the generic extractor preamble + ``_SKILL``. The extractor base
    template told the model to "return null when not found" — and on a
    ``TargetSchema`` the only nullable shape is ``{}``, which is what
    the model produced on messy workbooks. Drop the template; use
    ``_SKILL`` whole.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _SKILL, _make_discovery_agent

    agent = _make_discovery_agent("anthropic:claude-sonnet-4-6")
    # FireflyAgent stores instructions on the underlying pydantic_ai
    # agent; surface them by re-reading the same source-of-truth.
    assert agent.name == "schema_discovery"
    # The unit-inference guidance must still reach the model.
    assert "Unit inference" in _SKILL
    # And the extractor preamble that conflicted with the output
    # contract must NOT be silently merged back in.
    assert "If a field cannot be found, return null" not in _SKILL


# ---- Header-row detection for messy Excel sheets ------------------------
#
# Real-world Excel files often have a "section numbers" or "decorative
# title" row above the actual column headers. The first ``_excel_sample``
# heuristic ("first row with ≥2 non-null cells") picked those banner rows
# as headers, leaving the LLM to interpret integers/Nones as field names
# and the real headers as a sample row. That confused the model enough
# that it returned an empty schema and pydantic-ai retried 3× then gave
# up — the user-reported #170 follow-up bug.


def test_pick_header_row_idx_skips_numeric_banner_row():
    """Row 0 holds section numbers (1, 2, 3, …); row 1 holds the real
    string headers. The picker must select row 1.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _pick_header_row_idx

    rows = [
        (None, None, 1, 2, 3, 4, None),
        ("PRID", "EMPLOYEE_ID", "NAME", "REGION", "REVENUE", "COST", "NOTES"),
        ("test001", 4286, "Alice", "EU", 1000.0, 800.0, "-"),
    ]
    assert _pick_header_row_idx(rows) == 1


def test_pick_header_row_idx_skips_single_cell_title_row():
    """Decorative title rows have only one non-null cell. Skip them
    even when the row immediately after looks header-shaped.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _pick_header_row_idx

    rows = [
        ("Sales report — Q3 2024", None, None, None),
        ("region", "amount", "currency", "notes"),
        ("EU", 1000, "EUR", "ok"),
    ]
    assert _pick_header_row_idx(rows) == 1


def test_pick_header_row_idx_returns_zero_on_well_formed_sheet():
    """Existing well-formed sheets keep working: row 0 is already a
    string-dominant header row, no skip needed.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _pick_header_row_idx

    rows = [
        ("region", "amount", "currency"),
        ("EU", 1000, "EUR"),
        ("NA", 1500, "USD"),
    ]
    assert _pick_header_row_idx(rows) == 0


def test_pick_header_row_idx_returns_zero_when_no_string_header_visible():
    """All-numeric sheets (e.g. a pure metrics dump) have no string
    header at all; the picker falls back to the first multi-cell row
    rather than refusing to choose. The LLM can still attempt naming
    from sample-row context.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _pick_header_row_idx

    rows = [
        (1, 2, 3, 4),
        (10, 20, 30, 40),
        (100, 200, 300, 400),
    ]
    assert _pick_header_row_idx(rows) == 0


def test_skill_prompt_requires_non_empty_schema():
    """Output-contract guard added to ``_SKILL`` after a user-reported
    failure where the discovery LLM returned ``{}`` on messy data and
    pydantic-ai's retry budget ran out before producing anything
    usable. The prompt must explicitly forbid the empty-schema escape.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _SKILL

    assert "Output contract" in _SKILL, "must lead with the output-contract clause"
    # Imperative voice that the model can't dismiss.
    assert "ALWAYS return" in _SKILL
    assert "never the right answer" in _SKILL.lower() or "is never the right" in _SKILL.lower()
    # Specifically marks the unit-related conservatism as the *exception*,
    # not the rule — otherwise the model generalises "be conservative" to
    # the whole schema and returns ``{}``.
    assert "ONLY to the" in _SKILL or "only to the" in _SKILL.lower()


# ---- Real-world workbook regression: the source workbook ----
#
# After the first fix (`e9e4dc8`) the user re-ran discovery on a Mexican
# sales-tracking workbook with eight sheets and still hit
# ``ValidationError: tables Field required, input_value={}``. Offline
# investigation against the actual file showed three concrete defects
# that the first fix didn't cover:
#
#   * One sheet (``an archive sheet``) has the real header at row 8 —
#     past the prior 8-row scan window, so the picker returned 0 and
#     the sample for that sheet was six rows of mostly-None garbage.
#   * One sheet (``pivot sheet``) has a 2-cell decorative title at row 0
#     ``['DECORATIVE TITLE', '(en blanco)']`` that satisfies every
#     "string-dominated, multi-cell" rule yet isn't the real header.
#     The real header sits at row 2 with five string cells.
#   * One sheet (``Sheet1``) is essentially blank but openpyxl still
#     reports three rows, so it leaked a ``Headers: [None, None, None]``
#     block into the LLM prompt, biasing the model toward empty output.


def test_pick_header_row_idx_finds_header_past_row_eight():
    """Hard regression for ``an archive sheet``: scan window must reach
    far enough to find the real header at row 8. With the prior ``[:8]``
    cap the header was literally invisible.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _pick_header_row_idx

    rows = [
        (None, None, None, None, None, None, None, None, None, "LEGEND ENTRY 1", None, None),
        (None, None, None, None, None, None, None, None, None, "LEGEND ENTRY 2", None, None),
        (None, None, None, None, None, None, None, None, None, "LEGEND ENTRY 3", None, None),
        (None, None, None, None, None, None, None, None, None, "LEGEND ENTRY 4", None, None),
        (None, None, None, None, None, None, None, None, None, "LEGEND ENTRY 5", None, None),
        (None, None, None, None, None, None, None, None, None, None, None, None),
        (None, None, None, None, None, None, None, None, None, None, None, None),
        (None, None, None, None, None, None, None, None, None, None, None, None),
        (
            None,
            "PRID",
            "NUMERO DE EMPLEADO",
            "NO. WORK DAY",
            "FECHA DE INGRESO",
            "CENTRO DE COSTOS",
            "RUTA",
            "GENERO",
            "NOMBRE EMPLEADO",
            "POSICION",
            "LOCALIDAD",
            "UNIDAD DE NEGOCIO",
        ),
        (
            None,
            "test001",
            1001,
            9000001,
            "2020-01-15",
            100000,
            200001,
            "M",
            "ANON EMPLOYEE ONE",
            "DIRECTOR",
            "REGION-A",
            "UNIT-X",
        ),
    ]
    assert _pick_header_row_idx(rows) == 8


def test_pick_header_row_idx_prefers_wider_real_header_over_decorative_title():
    """Hard regression for ``pivot sheet``: a 2-cell decorative title satisfies
    every previous rule (multi-cell, 100% string-dominant) but isn't the
    real header. The picker must prefer the wider 5-cell header below.
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _pick_header_row_idx

    rows = [
        ("DECORATIVE TITLE", "(en blanco)", None, None, None),
        (None, None, None, None, None),
        (
            "Etiquetas de fila",
            "Average Score",
            "Cuenta de TOTAL INTERACCIONES",
            "Promedio de AVG INTERACCIONES",
            "Suma de Eventos",
        ),
        ("REPRESENTANTE", 1.04, 346, 8.71, 3822),
        ("BREAST CANCER", 1.00, 13, 5.44, 149),
    ]
    assert _pick_header_row_idx(rows) == 2


@pytest.mark.asyncio
async def test_discover_schema_raises_with_diagnostic_on_empty_output(csv_file: Path) -> None:
    """When the LLM returns an empty schema, ``discover_schema`` must
    raise ``ValueError`` with sheet/source context + a truncated sample,
    NOT propagate pydantic-ai's terse ``Field required`` retry storm.
    """
    mock_result = MagicMock()
    mock_result.output = TargetSchema()  # default empty tables list

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        with pytest.raises(ValueError) as exc_info:
            await discover_schema(csv_file)

    msg = str(exc_info.value)
    # Source label.
    assert "sales.csv" in msg
    # Actionable remediation.
    assert "corrections=" in msg
    # Sample echoed back so the user / agent can see what the model saw.
    assert "Sample sent to the model" in msg


def test_target_schema_defaults_tables_to_empty_list():
    """``TargetSchema()`` must accept ``{}`` and produce ``tables=[]``.
    The prior ``list[TableSpec]`` required-field shape made every empty
    LLM output trigger pydantic-ai's retry-on-validation loop, which
    masked the real failure mode with an opaque ``UnexpectedModelBehavior``.
    """
    s = TargetSchema.model_validate({})
    assert s.tables == []
    s2 = TargetSchema()
    assert s2.tables == []


@pytest.mark.asyncio
async def test_discover_schema_refinement_empty_calls_out_discarded_baseline(
    csv_file: Path,
) -> None:
    """When the LLM returns ``{}`` during a *refinement* call (a
    ``previous_schema`` was supplied), the error must frame it as the
    model discarding a validated baseline — not as "couldn't find any
    tables." This is the failure we saw on the real ingestion test:
    refinement returned empty despite having 8 prior tables to carry
    forward. Without this differentiated diagnostic the user can't
    tell whether to clean up the file or retry with simpler edits.
    """
    prior = TargetSchema(
        tables=[
            TableSpec(name="x", columns=[ColumnSpec(name="id", type=ColumnType.integer)]),
            TableSpec(name="y", columns=[ColumnSpec(name="id", type=ColumnType.integer)]),
        ]
    )
    mock_result = MagicMock()
    mock_result.output = TargetSchema()  # empty

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_factory.return_value = mock_agent
        with pytest.raises(ValueError) as exc_info:
            await discover_schema(csv_file, corrections="drop table y", previous_schema=prior)

    msg = str(exc_info.value)
    # Specifically frames the failure as refinement, not initial discovery.
    assert "refinement" in msg.lower()
    # Surfaces the baseline that was thrown away.
    assert "x" in msg and "y" in msg
    # Echoes back what the user said so they can adjust.
    assert "drop table y" in msg


def test_skill_prompt_allows_composite_primary_keys():
    """``_SKILL`` must teach the model that multiple primary_key=True
    columns form a composite key. Otherwise the prior "At most one
    primary key per table" wording leaves the model unable to express
    real-world identity like (employee_id, route).
    """
    from fireflyframework_agentic.rag.ingest.structured_registry import _SKILL

    assert "composite primary key" in _SKILL.lower()
    # The previous restrictive line must be gone, otherwise the model
    # gets contradictory guidance and falls back to single-PK.
    assert "At most one primary key" not in _SKILL


@pytest.mark.asyncio
async def test_discover_schema_retries_once_on_empty_output(csv_file: Path) -> None:
    """The LLM is non-deterministic on borderline-messy inputs — same
    sample produces non-empty most runs and ``{}`` on a minority. One
    Python-side retry turns the flaky pass rate into a reliable one.
    The retry must include the original prompt plus a short nudge so
    the model knows what changed.
    """
    expected = TargetSchema(tables=[TableSpec(name="sales", columns=[ColumnSpec(name="id", type=ColumnType.integer)])])
    empty_result = MagicMock(output=TargetSchema())
    good_result = MagicMock(output=expected)

    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        # First call returns empty; second returns the good schema.
        mock_agent.run = AsyncMock(side_effect=[empty_result, good_result])
        mock_factory.return_value = mock_agent
        result = await discover_schema(csv_file)

    assert result.tables[0].name == "sales"
    assert mock_agent.run.await_count == 2
    # Second call must have the nudge appended.
    second_prompt = mock_agent.run.call_args_list[1][0][0]
    assert "previous response contained no tables" in second_prompt


@pytest.mark.asyncio
async def test_discover_schema_does_not_retry_when_first_attempt_succeeds(
    csv_file: Path,
) -> None:
    """The retry is only there for empty-output recovery — don't waste
    an API call when the first attempt already produced tables.
    """
    expected = TargetSchema(tables=[TableSpec(name="sales", columns=[ColumnSpec(name="id", type=ColumnType.integer)])])
    with patch("fireflyframework_agentic.rag.ingest.structured_registry._make_discovery_agent") as mock_factory:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=MagicMock(output=expected))
        mock_factory.return_value = mock_agent
        await discover_schema(csv_file)

    assert mock_agent.run.await_count == 1


def test_discover_schema_refinement_prompt_documents_contract():
    """The discovery prompt for refinement must teach the model to
    carry unchanged tables forward and only omit on explicit drop/remove
    corrections. Without this we kept hitting empty-on-refinement on
    real ingest runs.
    """
    import inspect

    from fireflyframework_agentic.rag.ingest import structured_registry

    src = inspect.getsource(structured_registry)
    assert "Refinement contract" in src
    # Single-path and multi-path discovery both need it.
    assert src.count("Refinement contract") >= 2


def test_excel_sample_skips_sheets_with_no_usable_header(tmp_path: Path) -> None:
    """``_excel_sample`` must drop sheets whose chosen header row is
    structurally empty (no strings or <2 non-null cells). Such sheets
    surfaced as ``Headers: [None, None, None]`` blocks in the LLM
    prompt and biased the model toward returning ``{}``.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from fireflyframework_agentic.rag.ingest.structured_registry import _excel_sample

    wb = openpyxl.Workbook()
    # Default sheet — ghost: empty + one stray note at row 3.
    ghost = wb.active
    ghost.title = "Ghost"
    ghost["C3"] = "stray note"
    # Real sheet with a clean header row.
    real = wb.create_sheet("Real")
    real.append(["id", "name", "amount"])
    real.append([1, "Alice", 9.99])
    real.append([2, "Bob", 19.99])
    xlsx = tmp_path / "mixed.xlsx"
    wb.save(xlsx)

    sample = _excel_sample(xlsx)
    assert "Sheet (table): real" in sample
    assert "Sheet (table): ghost" not in sample
    assert "[None, None, None]" not in sample


def test_excel_sample_finds_header_deep_in_sheet(tmp_path: Path) -> None:
    """End-to-end regression for the ``an archive sheet`` pattern: a
    sheet whose real header sits at row 9 (past the prior 8-row scan
    window) must still produce a sample with that header as ``Headers:``.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from fireflyframework_agentic.rag.ingest.structured_registry import _excel_sample

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deep"
    # 8 single-cell decorative title rows.
    for i in range(8):
        ws.cell(row=i + 1, column=10, value=f"TITLE LINE {i + 1}")
    # Real header at row 9, with a leading-blank column (matches the
    # workbook layout where column A is empty and B onward is data).
    ws.append([None, "PRID", "EMPLOYEE_ID", "NAME", "REGION"])
    ws.append([None, "test001", 1001, "ANON_PERSON", "REGION-A"])
    xlsx = tmp_path / "deep.xlsx"
    wb.save(xlsx)

    sample = _excel_sample(xlsx)
    assert "PRID" in sample
    assert "EMPLOYEE_ID" in sample
    # The decorative title should NOT have been mistaken for headers.
    assert "TITLE LINE" not in sample.split("Headers:", 1)[1].split("\n", 1)[0]
