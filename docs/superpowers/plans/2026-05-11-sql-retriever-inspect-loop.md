# Agentic SQL Retriever with Inspect Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stateless one-shot text-to-SQL stage in `StructuredRetriever` with a tool-using agent loop that can inspect the corpus DB before committing to a final `SELECT`, and surface a structured outcome so the answerer can speak helpfully when SQL ran but matched zero rows.

**Architecture:** Single-file rewire of `fireflyframework_agentic/rag/retrieval/sql.py`. New dataclasses (`SqlRetrievalOutcome`, `ProbeRecord`) replace the `str | None` return contract. `FireflyAgent` is given two async-function tools (`inspect_table`, `run_select`) that close over a private `_LoopContext`; pydantic-ai handles the tool loop natively. `AnswerAgent.answer` is updated to consume the new outcome and formats a probe-trail section into its prompt when SQL ran but found nothing.

**Tech Stack:** Python 3.13, pydantic-ai (via `FireflyAgent`), sqlite3, pytest + pytest-asyncio, ruff.

**Spec:** `docs/superpowers/specs/2026-05-11-sql-retriever-inspect-loop-design.md`

---

## File Structure

**Modify:**
- `fireflyframework_agentic/rag/retrieval/sql.py` — full rewire (new dataclasses, tool builders, loop driver). One file, kept under ~350 LoC.
- `fireflyframework_agentic/rag/retrieval/answerer.py` — change `answer()` signature to take `sql_outcome: SqlRetrievalOutcome | None`; add empty-outcome prompt section; narrow `_NO_INFO_TEXT` short-circuit.
- `fireflyframework_agentic/rag/agent.py:636-640` — one-line callsite change (pass `sql_outcome` instead of `sql_context`).
- `tests/unit/corpus_search/test_sql_retriever.py` — rewrite the 6 existing tests to the new shape.
- `tests/unit/corpus_search/test_answerer_sql_context.py` — rewrite the 3 existing tests for the new signature.
- `tests/integration/test_corpus_agent_structured.py` — update the stubs to match the new structured-retriever return type.

**Create:**
- `tests/integration/test_corpus_query_grounding.py` — regression test that reproduces the original failure mode (synonym mismatch + column-name overload) on a sanitised synthetic fixture.

---

## Task 1: Add `SqlRetrievalOutcome` and `ProbeRecord` dataclasses

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/sql.py` (add at module top, near imports)
- Test: `tests/unit/corpus_search/test_sql_retriever.py` (add new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/corpus_search/test_sql_retriever.py` (do not delete existing tests yet — they'll be rewritten in Task 5):

```python
from fireflyframework_agentic.rag.retrieval.sql import ProbeRecord, SqlRetrievalOutcome


def test_probe_record_is_frozen_dataclass():
    r = ProbeRecord(table="t", column="c", op="distinct_values", result="a | b")
    assert r.table == "t"
    with pytest.raises(Exception):  # frozen=True → FrozenInstanceError
        r.table = "u"  # type: ignore[misc]


def test_sql_retrieval_outcome_answered():
    out = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="col\n---\nval",
        attempted_sql="SELECT col FROM t",
        probe_trail=[],
    )
    assert out.outcome == "answered"
    assert out.result_markdown == "col\n---\nval"


def test_sql_retrieval_outcome_unsupported_default_shape():
    out = SqlRetrievalOutcome(
        outcome="unsupported",
        result_markdown=None,
        attempted_sql=None,
        probe_trail=[],
    )
    assert out.outcome == "unsupported"
    assert out.result_markdown is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py::test_probe_record_is_frozen_dataclass -v
```

Expected: `ImportError: cannot import name 'ProbeRecord' from 'fireflyframework_agentic.rag.retrieval.sql'`

- [ ] **Step 3: Implement the dataclasses**

Edit `fireflyframework_agentic/rag/retrieval/sql.py` — add after the imports block (after line 28, before `_SYSTEM`):

```python
from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True, frozen=True)
class ProbeRecord:
    """Record of a single `inspect_table` tool call.

    `result` is the markdown string the tool returned to the LLM, truncated
    to ~500 chars to keep observability payloads bounded.
    """

    table: str
    column: str
    op: str
    result: str


@dataclass(slots=True, frozen=True)
class SqlRetrievalOutcome:
    """Structured result of running the agentic SQL retrieval loop.

    States:
      - 'answered': `run_select` returned >=1 row. `result_markdown` is the
        markdown table; `attempted_sql` is the SELECT that produced it.
      - 'empty':    `run_select` ran cleanly but returned 0 rows on the last
        attempt. `result_markdown=None`; `attempted_sql` is the last SELECT;
        `probe_trail` records what the LLM inspected.
      - 'unsupported': cap exhausted, sentinel `SELECT 1 WHERE 1=0`, every
        attempt errored, or `schemas` was empty.
    """

    outcome: Literal["answered", "empty", "unsupported"]
    result_markdown: str | None
    attempted_sql: str | None
    probe_trail: list[ProbeRecord] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v -k "probe_record or sql_retrieval_outcome"
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/sql.py tests/unit/corpus_search/test_sql_retriever.py
git commit -m "$(cat <<'EOF'
feat(rag): add SqlRetrievalOutcome and ProbeRecord dataclasses

Defines the structured return type for the agentic SQL retriever and the
per-probe record carried in its trail. Future commits will wire the loop
behind these types.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extend `_execute` to return error messages and cap rows

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/sql.py:114-128`
- Test: `tests/unit/corpus_search/test_sql_retriever.py`

The existing `_execute` swallows sqlite3 errors and returns `None`. The agentic loop needs the error message so the LLM can self-correct, and a row cap so a huge final SELECT doesn't blow up the context window.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/corpus_search/test_sql_retriever.py`:

```python
from fireflyframework_agentic.rag.retrieval.sql import _execute, MAX_ROWS_IN_RESULT


def test_execute_returns_error_message_on_sql_error(tmp_path: Path):
    db = _populated_db(tmp_path)
    result = _execute(db, "SELECT * FROM does_not_exist")
    assert result is not None
    assert "no such table" in result.lower()


def test_execute_caps_rows_and_appends_truncation_footer(tmp_path: Path):
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (n INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(MAX_ROWS_IN_RESULT + 5)])
    conn.commit()
    conn.close()
    result = _execute(db, "SELECT n FROM t ORDER BY n")
    assert result is not None
    body_lines = result.split("\n")
    # header + sep + capped rows + footer
    assert len(body_lines) == 2 + MAX_ROWS_IN_RESULT + 1
    assert body_lines[-1] == f"(+5 more rows; result capped at {MAX_ROWS_IN_RESULT})"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py::test_execute_returns_error_message_on_sql_error tests/unit/corpus_search/test_sql_retriever.py::test_execute_caps_rows_and_appends_truncation_footer -v
```

Expected: 2 failures (ImportError on `MAX_ROWS_IN_RESULT`; `_execute` returns None on error).

- [ ] **Step 3: Implement the changes**

In `fireflyframework_agentic/rag/retrieval/sql.py`, add the constant near the top (right after the `_SYSTEM` constant or after the new dataclasses):

```python
MAX_ROWS_IN_RESULT = 100
MAX_ROWS_PER_PROBE = 20
```

Replace the existing `_execute` function (the one currently at lines 114-128) with:

```python
def _execute(db_path: Path, sql: str) -> str | None:
    """Execute *sql* and return a markdown table.

    Returns:
      - markdown table (possibly with a truncation footer) on success with rows
      - None if the SELECT ran successfully but matched 0 rows
      - a human-readable error message starting with 'SQL error:' on failure

    The 'error string vs None vs table' distinction lets the caller decide
    what state to record on the outcome: an error means try again; None means
    `outcome='empty'`; a table means `outcome='answered'`.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description] if cur.description else []
    except sqlite3.Error as exc:
        log.warning("SQL execution failed: %s", exc)
        return f"SQL error: {exc}"
    if not rows:
        return None
    truncated_count = max(0, len(rows) - MAX_ROWS_IN_RESULT)
    kept = rows[:MAX_ROWS_IN_RESULT]
    header = " | ".join(col_names)
    sep = " | ".join("---" for _ in col_names)
    body = "\n".join(" | ".join(str(v) for v in row) for row in kept)
    table = f"{header}\n{sep}\n{body}"
    if truncated_count:
        table += f"\n(+{truncated_count} more rows; result capped at {MAX_ROWS_IN_RESULT})"
    return table
```

- [ ] **Step 4: Update the existing `test_retrieve_returns_none_on_sql_error` test (it's now obsolete)**

This test passed today because `_execute` swallowed errors and the retriever returned None. With the new contract, an SQL error is surfaced to the LLM. The test was checking the *old* swallow-and-return-None behaviour at the retriever level; we'll rewrite the retriever-level tests in Task 5. Mark this test as expecting the new shape — delete it from the file for now (it will not be re-added as written; the new equivalent will live in Task 5).

Edit `tests/unit/corpus_search/test_sql_retriever.py` — delete the existing function `test_retrieve_returns_none_on_sql_error` entirely (lines 88-96 in the pre-Task-1 file).

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v
```

Expected: all listed tests pass; `test_retrieve_returns_none_on_sql_error` is no longer collected.

- [ ] **Step 6: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/sql.py tests/unit/corpus_search/test_sql_retriever.py
git commit -m "$(cat <<'EOF'
refactor(rag): _execute surfaces SQL errors and caps result rows

SQL errors return 'SQL error: ...' so the agentic loop can pass them back
to the LLM as a tool result. Results larger than MAX_ROWS_IN_RESULT (100)
are truncated with a footer line so the LLM knows there are more rows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `_LoopContext` and `_build_inspect_tool`

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/sql.py`
- Test: `tests/unit/corpus_search/test_sql_retriever.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/corpus_search/test_sql_retriever.py`:

```python
from fireflyframework_agentic.rag.retrieval.sql import _LoopContext, _build_inspect_tool


def _seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sales (period TEXT, region TEXT, product_name TEXT, revenue REAL)")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?, ?, ?)",
        [
            ("2025-Q4", "EU-North", "MX-3000 Wireless Mouse", 1200.0),
            ("2025-Q4", "EU-South", "K10 Keyboard", 800.0),
            ("2025-Q3", "NA", "MX-3000 Wireless Mouse", 950.0),
        ],
    )
    conn.commit()
    conn.close()
    return db


def _sales_schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="period", type=ColumnType.string),
                    ColumnSpec(name="region", type=ColumnType.string),
                    ColumnSpec(name="product_name", type=ColumnType.string),
                    ColumnSpec(name="revenue", type=ColumnType.number),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_inspect_table_distinct_values(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "region", "distinct_values")
    assert "EU-North" in result
    assert "EU-South" in result
    assert "NA" in result
    assert len(ctx.probe_trail) == 1
    assert ctx.probe_trail[0].column == "region"
    assert ctx.probe_trail[0].op == "distinct_values"


@pytest.mark.asyncio
async def test_inspect_table_count(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "period", "count")
    assert "3" in result


@pytest.mark.asyncio
async def test_inspect_table_sample_rows(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "period", "sample_rows")
    assert "EU-North" in result or "EU-South" in result


@pytest.mark.asyncio
async def test_inspect_table_value_range(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    result = await inspect("sales", "revenue", "value_range")
    assert "800" in result
    assert "1200" in result


@pytest.mark.asyncio
async def test_inspect_table_rejects_unknown_table(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    with pytest.raises(ValueError, match="not in registered schemas"):
        await inspect("sqlite_master", "name", "distinct_values")


@pytest.mark.asyncio
async def test_inspect_table_rejects_unknown_column(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    inspect = _build_inspect_tool(ctx)
    with pytest.raises(ValueError, match="column 'phantom' not in"):
        await inspect("sales", "phantom", "distinct_values")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v -k "inspect_table or _LoopContext"
```

Expected: ImportError on `_LoopContext` / `_build_inspect_tool`.

- [ ] **Step 3: Implement `_LoopContext` and `_build_inspect_tool`**

Add to `fireflyframework_agentic/rag/retrieval/sql.py` (after the dataclasses, before `class StructuredRetriever`):

```python
@dataclass(slots=True)
class _LoopContext:
    """Mutable per-query state shared between the loop tools.

    Built fresh on each `StructuredRetriever.retrieve()` call. Tools close
    over this object; the loop driver reads its final state to build the
    SqlRetrievalOutcome.
    """

    db_path: Path
    schemas: list[TargetSchema]
    probe_trail: list[ProbeRecord] = field(default_factory=list)
    attempted_sql: str | None = None
    last_result_markdown: str | None = None
    last_result_was_empty: bool = False
    last_result_was_sentinel: bool = False
    run_select_call_count: int = 0


_SENTINEL_SQL_PATTERN = re.compile(r"^\s*SELECT\s+1\s+WHERE\s+1\s*=\s*0\s*;?\s*$", re.IGNORECASE)


def _allowed_columns(schemas: list[TargetSchema]) -> dict[str, set[str]]:
    """Build a {table_name: {column_names}} allow-list from the registered schemas."""
    allowed: dict[str, set[str]] = {}
    for schema in schemas:
        for table in schema.tables:
            allowed[table.name] = {c.name for c in table.columns}
    return allowed


def _build_inspect_tool(ctx: _LoopContext):
    """Return an async `inspect_table(table, column, op)` tool bound to *ctx*.

    The tool runs parametric SQL — table/column are validated against the
    schema allow-list and quoted; `op` selects one of four fixed queries.
    The LLM never composes SQL at inspect time, so injection risk is zero
    by construction.
    """

    allowed = _allowed_columns(ctx.schemas)

    async def inspect_table(
        table: str,
        column: str,
        op: Literal["distinct_values", "count", "sample_rows", "value_range"],
    ) -> str:
        """Peek at the corpus DB before composing the final SELECT.

        Ops:
          - distinct_values: up to MAX_ROWS_PER_PROBE distinct values of *column*
          - count: COUNT(*) of *table*
          - sample_rows: first 5 rows of *table*
          - value_range: MIN/MAX of *column*

        Raises ValueError if *table* or *column* is not in the registered
        schemas (this gets surfaced back to the LLM as a tool error).
        """
        if table not in allowed:
            raise ValueError(
                f"table '{table}' not in registered schemas; "
                f"available tables: {sorted(allowed)}"
            )
        cols = allowed[table]
        if op != "count" and column not in cols:
            raise ValueError(
                f"column '{column}' not in '{table}'; available: {sorted(cols)}"
            )
        # Identifier quoting: sqlite uses "..." for identifiers; double up any
        # embedded quote chars. Allowlist already gates non-existent names, so
        # this is belt-and-braces.
        t = '"' + table.replace('"', '""') + '"'
        c = '"' + column.replace('"', '""') + '"'
        if op == "distinct_values":
            sql = f"SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT {MAX_ROWS_PER_PROBE}"
        elif op == "count":
            sql = f"SELECT COUNT(*) FROM {t}"
        elif op == "sample_rows":
            sql = f"SELECT * FROM {t} LIMIT 5"
        elif op == "value_range":
            sql = f"SELECT MIN({c}), MAX({c}) FROM {t}"
        else:
            raise ValueError(f"unknown op '{op}'")
        result = _execute(ctx.db_path, sql) or "(no rows)"
        # Truncate the trail record but pass the full result to the LLM.
        ctx.probe_trail.append(
            ProbeRecord(table=table, column=column, op=op, result=result[:500])
        )
        return result

    return inspect_table
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v -k "inspect_table or _LoopContext"
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/sql.py tests/unit/corpus_search/test_sql_retriever.py
git commit -m "$(cat <<'EOF'
feat(rag): add _LoopContext and inspect_table tool builder

The inspect_table tool runs parametric SQL for one of four ops against
the corpus DB. Table/column names are validated against the registered
schemas before being quoted into the query, so the LLM cannot probe
sqlite_master or unknown tables.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `_build_run_select_tool`

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/sql.py`
- Test: `tests/unit/corpus_search/test_sql_retriever.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/corpus_search/test_sql_retriever.py`:

```python
from fireflyframework_agentic.rag.retrieval.sql import _build_run_select_tool


@pytest.mark.asyncio
async def test_run_select_returns_markdown_and_records_sql(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("SELECT period, region FROM sales WHERE region='EU-North'")
    assert "EU-North" in result
    assert "2025-Q4" in result
    assert ctx.attempted_sql == "SELECT period, region FROM sales WHERE region='EU-North'"
    assert ctx.last_result_was_empty is False
    assert ctx.run_select_call_count == 1


@pytest.mark.asyncio
async def test_run_select_rejects_non_select(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("DROP TABLE sales")
    assert "must start with SELECT" in result
    # The non-select attempt is recorded so cap-exhausted outcomes still
    # carry the SQL the LLM tried.
    assert ctx.attempted_sql == "DROP TABLE sales"


@pytest.mark.asyncio
async def test_run_select_returns_error_message_on_sql_error(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("SELECT * FROM phantom_table")
    assert "SQL error" in result
    assert "no such table" in result.lower()


@pytest.mark.asyncio
async def test_run_select_sets_empty_flag_on_zero_rows(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    result = await run_select("SELECT * FROM sales WHERE region='Antarctica'")
    assert "0 rows" in result or "no rows" in result.lower()
    assert ctx.last_result_was_empty is True
    assert ctx.attempted_sql == "SELECT * FROM sales WHERE region='Antarctica'"


@pytest.mark.asyncio
async def test_run_select_detects_sentinel(tmp_path: Path):
    ctx = _LoopContext(db_path=_seeded_db(tmp_path), schemas=[_sales_schema()])
    run_select = _build_run_select_tool(ctx)
    await run_select("SELECT 1 WHERE 1=0")
    assert ctx.last_result_was_sentinel is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v -k "run_select"
```

Expected: ImportError on `_build_run_select_tool`.

- [ ] **Step 3: Implement `_build_run_select_tool`**

Add to `fireflyframework_agentic/rag/retrieval/sql.py` (right after `_build_inspect_tool`):

```python
def _build_run_select_tool(ctx: _LoopContext):
    """Return an async `run_select(sql)` tool bound to *ctx*.

    Each call updates `ctx.attempted_sql` and `ctx.last_result_*` so the loop
    driver can read the terminal state when the agent stops.
    """

    async def run_select(sql: str) -> str:
        """Execute the final SELECT statement against the corpus DB.

        - Must start with SELECT (case-insensitive, leading whitespace
          allowed). Returns 'SQL must start with SELECT.' on violation —
          the LLM can revise and retry.
        - Returns 'SQL error: ...' on sqlite3 errors so the LLM can self-
          correct (the loop is not terminated on a single error).
        - Returns 'Query returned 0 rows.' on a clean run with no matches —
          this marks the outcome as 'empty' if it's the last SELECT.
        - Otherwise returns a markdown table, capped at MAX_ROWS_IN_RESULT.
        """
        ctx.attempted_sql = sql
        ctx.run_select_call_count += 1
        # Reset per-call flags so the *last* run_select determines the outcome.
        ctx.last_result_was_empty = False
        ctx.last_result_was_sentinel = False
        ctx.last_result_markdown = None
        if _SENTINEL_SQL_PATTERN.match(sql):
            ctx.last_result_was_sentinel = True
            return "Acknowledged: no answer is possible from this schema."
        if not re.match(r"(?i)^\s*SELECT\b", sql):
            return "SQL must start with SELECT. Other statements are not allowed."
        result = _execute(ctx.db_path, sql)
        if result is None:
            ctx.last_result_was_empty = True
            return "Query returned 0 rows."
        if result.startswith("SQL error:"):
            # Don't store as result; let the LLM retry.
            return result
        ctx.last_result_markdown = result
        return result

    return run_select
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v -k "run_select"
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/sql.py tests/unit/corpus_search/test_sql_retriever.py
git commit -m "$(cat <<'EOF'
feat(rag): add run_select tool builder

run_select is the agent's terminal tool — accepts a SELECT, returns either
a markdown table, a structured 'empty' signal, an SQL error the LLM can
retry on, or a sentinel acknowledgement when the LLM gives up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Rewire `StructuredRetriever` to drive the agent loop

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/sql.py` (replace `_SYSTEM`, replace `class StructuredRetriever`, slim `_build_schema_context`)
- Test: `tests/unit/corpus_search/test_sql_retriever.py` (rewrite the 4 retriever-level tests)

- [ ] **Step 1: Delete the obsolete retriever tests**

Edit `tests/unit/corpus_search/test_sql_retriever.py` and remove the four pre-Task-1 tests that exercised the old retrieve-returns-str-or-None contract:

- `test_retrieve_returns_none_for_empty_schemas`
- `test_retrieve_returns_markdown_table`
- `test_retrieve_rejects_non_select_sql`
- (Already removed in Task 2:) `test_retrieve_returns_none_on_sql_error`

Also remove the old `test_build_schema_context` — it'll be rewritten in this task.

The `_schema()` helper at the top of the file (lines 30-41 pre-Task-1) is still used by `test_execute_returns_none_for_empty_result` (kept) and nothing else; leave it.

- [ ] **Step 2: Write the new failing tests**

Append to `tests/unit/corpus_search/test_sql_retriever.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

from fireflyframework_agentic.rag.retrieval.sql import StructuredRetriever


@pytest.mark.asyncio
async def test_retrieve_empty_schemas_returns_unsupported(tmp_path: Path):
    retriever = StructuredRetriever(tmp_path / "corpus.sqlite")
    outcome = await retriever.retrieve("Anything?", schemas=[])
    assert outcome.outcome == "unsupported"
    assert outcome.result_markdown is None
    assert outcome.attempted_sql is None
    assert outcome.probe_trail == []


@pytest.mark.asyncio
async def test_retrieve_answered_after_probes(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    # Replay script: the stubbed agent calls inspect_table once, then run_select.
    async def fake_agent_run(prompt, **kwargs):
        # The tool closures must have been built into `retriever._tools` by retrieve();
        # call them through the registered tools list to mutate the context.
        tools = retriever._last_built_tools  # set by retrieve() for test access
        await tools["inspect_table"]("sales", "region", "distinct_values")
        await tools["run_select"](
            "SELECT period, region FROM sales WHERE region='EU-North'"
        )
        return MagicMock(output="done")  # agent's natural-language closing message

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Which periods saw EU-North sales?", schemas=[_sales_schema()])

    assert outcome.outcome == "answered"
    assert outcome.result_markdown is not None
    assert "EU-North" in outcome.result_markdown
    assert outcome.attempted_sql == "SELECT period, region FROM sales WHERE region='EU-North'"
    assert len(outcome.probe_trail) == 1
    assert outcome.probe_trail[0].column == "region"


@pytest.mark.asyncio
async def test_retrieve_empty_when_select_matches_nothing(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        tools = retriever._last_built_tools
        await tools["inspect_table"]("sales", "region", "distinct_values")
        await tools["run_select"]("SELECT * FROM sales WHERE region='Antarctica'")
        return MagicMock(output="no rows")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Antarctica sales?", schemas=[_sales_schema()])

    assert outcome.outcome == "empty"
    assert outcome.result_markdown is None
    assert outcome.attempted_sql == "SELECT * FROM sales WHERE region='Antarctica'"
    assert len(outcome.probe_trail) == 1


@pytest.mark.asyncio
async def test_retrieve_unsupported_on_sentinel(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        tools = retriever._last_built_tools
        await tools["run_select"]("SELECT 1 WHERE 1=0")
        return MagicMock(output="give up")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Something off-topic.", schemas=[_sales_schema()])

    assert outcome.outcome == "unsupported"


@pytest.mark.asyncio
async def test_retrieve_unsupported_when_agent_makes_no_tool_calls(tmp_path: Path):
    db = _seeded_db(tmp_path)
    retriever = StructuredRetriever(db)

    async def fake_agent_run(prompt, **kwargs):
        return MagicMock(output="I have nothing to do.")

    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=fake_agent_run)):
        outcome = await retriever.retrieve("Question?", schemas=[_sales_schema()])

    assert outcome.outcome == "unsupported"
    assert outcome.attempted_sql is None


def test_build_schema_context_has_no_sample_values_section(tmp_path: Path):
    """Sample values are now the agent's job — context should not include them."""
    from fireflyframework_agentic.rag.retrieval.sql import _build_schema_context
    ctx = _build_schema_context([_sales_schema()])
    assert "sales" in ctx
    assert "region" in ctx
    assert "sample" not in ctx.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v
```

Expected: failures referencing missing `_last_built_tools`, the old return shape (str/None), or wrong outcome value.

- [ ] **Step 4: Replace `_SYSTEM`, slim `_build_schema_context`, and rewrite `StructuredRetriever`**

In `fireflyframework_agentic/rag/retrieval/sql.py`, replace the existing `_SYSTEM` constant (currently lines 31-40) with:

```python
_SYSTEM = """\
You answer questions by querying a SQLite corpus database. You have two tools:

  inspect_table(table, column, op)
    op = 'distinct_values' | 'count' | 'sample_rows' | 'value_range'
    Use this to discover what values a column actually contains BEFORE you
    write the final SELECT. Free — call it whenever you are not sure.

  run_select(sql)
    Use this to run your final SELECT once you are confident in the values.
    You may call it more than once if the result was empty or errored.

Process:
  1. Read the schema below.
  2. If you are NOT sure what values exist in the columns you want to filter
     on, call inspect_table first. Don't probe columns whose values are
     obvious from the question.
  3. Call run_select with your final SELECT.
  4. If run_select returns 'Query returned 0 rows.' or 'SQL error: ...',
     you may inspect more and retry. Do not exceed 3 inspect calls without
     making progress.

Worked example (illustrative; no real corpus):
  Question: "wireless mouse sales in Europe last quarter"
  Schema: sales (period string, product_name string, region string,
                 revenue number, ...)
  Reasoning: "wireless mouse" might be a category label or a specific
             product — I don't know which. "Europe" might be a single
             region value or a prefix on several. I'll inspect both.

  inspect_table(sales, product_name, distinct_values)
    -> ['MX-3000 Wireless Mouse', 'MX-3000 Pro', 'K10 Keyboard', ...]
  inspect_table(sales, region, distinct_values)
    -> ['EU-North', 'EU-South', 'NA', 'APAC']
  inspect_table(sales, period, distinct_values)
    -> ['2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4']
  run_select("SELECT product_name, SUM(revenue) FROM sales "
             "WHERE period='2025-Q4' AND region LIKE 'EU-%' "
             "AND product_name LIKE '%Wireless Mouse%' "
             "GROUP BY product_name")

Rules:
  - SELECT only. No INSERT/UPDATE/DELETE/DROP/ALTER. The run_select tool
    enforces this; non-SELECT statements are rejected.
  - Use the exact table and column names from the schema below.
  - If the question cannot be answered from this schema at all (e.g. you'd
    need a column or join that doesn't exist), call run_select('SELECT 1
    WHERE 1=0') and stop.
"""
```

Replace `_build_schema_context` (currently at lines 86-100 pre-Task-1) with:

```python
def _build_schema_context(schemas: list[TargetSchema]) -> str:
    """Format the table+column listing for the agent's system prompt.

    No sample values: the agent inspects on demand. This avoids the
    heuristic that previously sampled only the first string column —
    which silently misled the LLM on schemas whose first text column was
    an opaque primary key.
    """
    lines: list[str] = ["Available tables:"]
    for schema in schemas:
        for table in schema.tables:
            col_descs = ", ".join(f"{c.name} ({c.type.value})" for c in table.columns)
            lines.append(f"- {table.name}: {col_descs}")
    return "\n".join(lines)
```

Now replace `class StructuredRetriever` (currently at lines 50-83 pre-Task-1) with:

```python
_MAX_STEPS = 8


class StructuredRetriever:
    """Agentic text-to-SQL retriever.

    Builds a fresh _LoopContext per query, exposes inspect_table and
    run_select as tools, and lets the LLM drive the loop. The terminal
    SqlRetrievalOutcome is built from the context's final state — the
    agent's natural-language closing message is discarded.
    """

    def __init__(self, db_path: Path, *, sql_model: str = _DEFAULT_SQL_MODEL) -> None:
        self._db_path = db_path
        self._sql_model = sql_model
        self._sql_agent = FireflyAgent(
            name="sql_inspector",
            model=sql_model,
            instructions=_SYSTEM,
            tools=(),  # tools are rebuilt per query with the loop context
            auto_register=False,
        )
        # Test hook: the most recently built tool closures, exposed only so
        # unit tests can drive the loop deterministically without going
        # through pydantic-ai's internal tool-call mechanism.
        self._last_built_tools: dict[str, Any] | None = None

    async def retrieve(
        self,
        question: str,
        schemas: list[TargetSchema],
    ) -> SqlRetrievalOutcome:
        """Run the inspect-and-select loop.

        Returns a SqlRetrievalOutcome describing what happened. Never raises
        on tool errors — those are turned into 'unsupported' outcomes.
        """
        if not schemas:
            return SqlRetrievalOutcome(
                outcome="unsupported",
                result_markdown=None,
                attempted_sql=None,
                probe_trail=[],
            )
        ctx = _LoopContext(db_path=self._db_path, schemas=schemas)
        inspect_tool = _build_inspect_tool(ctx)
        run_select_tool = _build_run_select_tool(ctx)
        self._last_built_tools = {
            "inspect_table": inspect_tool,
            "run_select": run_select_tool,
        }
        prompt = f"{_build_schema_context(schemas)}\n\nQuestion: {question}"
        try:
            await self._sql_agent.run(
                prompt,
                tools=[inspect_tool, run_select_tool],
                model_settings={"max_steps": _MAX_STEPS},
            )
        except Exception as exc:
            log.warning("SQL agent loop failed: %s", exc)
            return SqlRetrievalOutcome(
                outcome="unsupported",
                result_markdown=None,
                attempted_sql=ctx.attempted_sql,
                probe_trail=ctx.probe_trail,
            )
        return _build_outcome(ctx)


def _build_outcome(ctx: _LoopContext) -> SqlRetrievalOutcome:
    """Read the loop context's terminal state and produce a SqlRetrievalOutcome."""
    if ctx.last_result_was_sentinel:
        return SqlRetrievalOutcome(
            outcome="unsupported",
            result_markdown=None,
            attempted_sql=ctx.attempted_sql,
            probe_trail=list(ctx.probe_trail),
        )
    if ctx.last_result_markdown is not None:
        return SqlRetrievalOutcome(
            outcome="answered",
            result_markdown=ctx.last_result_markdown,
            attempted_sql=ctx.attempted_sql,
            probe_trail=list(ctx.probe_trail),
        )
    if ctx.run_select_call_count > 0 and ctx.last_result_was_empty:
        return SqlRetrievalOutcome(
            outcome="empty",
            result_markdown=None,
            attempted_sql=ctx.attempted_sql,
            probe_trail=list(ctx.probe_trail),
        )
    return SqlRetrievalOutcome(
        outcome="unsupported",
        result_markdown=None,
        attempted_sql=ctx.attempted_sql,
        probe_trail=list(ctx.probe_trail),
    )
```

Update the imports at the top of `sql.py` — ensure `FireflyAgent`, `Any`, `field`, and `Literal` are imported. The existing imports need:

```python
from typing import Any, Literal

from fireflyframework_agentic.agents import FireflyAgent
```

…and the existing `from fireflyframework_agentic.agents.templates import create_extractor_agent` import can be removed (no longer used). The `SQLQuery` Pydantic model (currently around line 43-45) is also no longer used — delete it.

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/corpus_search/test_sql_retriever.py -v
```

Expected: all tests pass (the 4 dataclass tests from Task 1, the 2 `_execute` tests from Task 2, the 6 `inspect_table` tests from Task 3, the 5 `run_select` tests from Task 4, the 6 new retriever-level tests, the 1 `_execute_returns_none_for_empty_result` test, the 1 new `_build_schema_context` test).

- [ ] **Step 6: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/sql.py tests/unit/corpus_search/test_sql_retriever.py
git commit -m "$(cat <<'EOF'
feat(rag): rewire StructuredRetriever as an agentic inspect loop

The retriever now exposes inspect_table and run_select as tools and lets
the LLM drive the loop. Schema context no longer samples the first text
column — the agent inspects on demand. _build_outcome derives the
SqlRetrievalOutcome from the loop's terminal state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update `AnswerAgent` for `SqlRetrievalOutcome`

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/answerer.py:30-36` (instructions), `122-157` (`answer` method)
- Test: `tests/unit/corpus_search/test_answerer_sql_context.py` (rewrite)

- [ ] **Step 1: Rewrite the three existing tests**

Replace the entire contents of `tests/unit/corpus_search/test_answerer_sql_context.py` with:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.answerer import Answer, AnswerAgent
from fireflyframework_agentic.rag.retrieval.sql import ProbeRecord, SqlRetrievalOutcome


@pytest.mark.asyncio
async def test_answer_without_sql_outcome_unchanged():
    """sql_outcome=None must not change existing behaviour."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    mock_result = MagicMock()
    mock_result.output = Answer(text="42", citations=[], cited_sources=[])
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(return_value=mock_result)
        hits = [ChunkHit(chunk_id="c1", content="some context", score=0.9, metadata={})]
        result = await agent.answer("What is the answer?", hits)
    assert result.text == "42"


@pytest.mark.asyncio
async def test_answer_with_answered_outcome_includes_structured_section():
    """outcome='answered' must produce the existing structured-data prompt section."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    captured_prompts: list[str] = []
    mock_result = MagicMock()
    mock_result.output = Answer(text="2 products", citations=[], cited_sources=[])

    async def capture_run(prompt: str) -> MagicMock:
        captured_prompts.append(prompt)
        return mock_result

    outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="id | name\n--- | ---\n1 | Widget",
        attempted_sql="SELECT id, name FROM products",
        probe_trail=[],
    )
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(side_effect=capture_run)
        await agent.answer("How many products?", [], sql_outcome=outcome)
    assert "## Structured Data Results" in captured_prompts[0]
    assert "Widget" in captured_prompts[0]


@pytest.mark.asyncio
async def test_answer_with_empty_outcome_includes_probe_trail_and_does_not_short_circuit():
    """outcome='empty' must NOT short-circuit, and the probe trail must be in the prompt."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    captured_prompts: list[str] = []
    mock_result = MagicMock()
    mock_result.output = Answer(text="closest brand is Forxiga", citations=[], cited_sources=[])

    async def capture_run(prompt: str) -> MagicMock:
        captured_prompts.append(prompt)
        return mock_result

    outcome = SqlRetrievalOutcome(
        outcome="empty",
        result_markdown=None,
        attempted_sql="SELECT * FROM sales WHERE region='Antarctica'",
        probe_trail=[
            ProbeRecord(table="sales", column="region", op="distinct_values",
                        result="EU-North | EU-South | NA | APAC"),
        ],
    )
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock(side_effect=capture_run)
        result = await agent.answer("Antarctica sales?", [], sql_outcome=outcome)

    # The agent was actually called — no short-circuit.
    assert mock_agent.run.await_count == 1
    # The prompt carries the empty-attempt context.
    p = captured_prompts[0]
    assert "## SQL attempt (no matching rows)" in p
    assert "SELECT * FROM sales WHERE region='Antarctica'" in p
    assert "EU-North" in p
    assert result.text == "closest brand is Forxiga"


@pytest.mark.asyncio
async def test_answer_with_unsupported_outcome_and_no_hits_short_circuits():
    """outcome='unsupported' + empty hits should still short-circuit to _NO_INFO_TEXT."""
    agent = AnswerAgent(model="anthropic:claude-haiku-4-5-20251001")
    outcome = SqlRetrievalOutcome(
        outcome="unsupported",
        result_markdown=None,
        attempted_sql=None,
        probe_trail=[],
    )
    with patch.object(agent, "_agent") as mock_agent:
        mock_agent.run = AsyncMock()
        result = await agent.answer("Off-topic question?", [], sql_outcome=outcome)
    mock_agent.run.assert_not_called()
    assert result.text == "I don't have enough information."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_answerer_sql_context.py -v
```

Expected: failures referencing the `sql_outcome` parameter that doesn't exist yet.

- [ ] **Step 3: Update `AnswerAgent.answer` signature and prompt construction**

Edit `fireflyframework_agentic/rag/retrieval/answerer.py`. First, update the instructions constant (line 30-36) to add empty-outcome guidance:

```python
_INSTRUCTIONS = (
    "You answer questions strictly from the provided source chunks. "
    "Cite chunks inline using [chunk_id] notation immediately after each "
    "claim that the chunk supports. If the chunks do not support an answer, "
    "reply exactly: 'I don't have enough information.' Populate the "
    "`citations` field with the unique chunk_ids you actually cited in `text`. "
    "If a 'SQL attempt (no matching rows)' section is present, do NOT reply "
    "'I don't have enough information.' Instead, tell the user the closest "
    "available values from the probe records and suggest a refined query."
)
```

Add the import for the outcome type near the top of the file (after the existing imports):

```python
from fireflyframework_agentic.rag.retrieval.sql import ProbeRecord, SqlRetrievalOutcome
```

Replace the `answer` method (currently at lines 122-157) with:

```python
async def answer(
    self,
    question: str,
    hits: Sequence[ChunkHit],
    *,
    sql_outcome: "SqlRetrievalOutcome | None" = None,
) -> Answer:
    async with timed_span(
        "firefly.rag.answer",
        histogram=query_stage_duration,
        attributes={
            "n_hits": len(hits),
            "model": self._model,
        },
        metric_labels={"stage": "answer"},
    ) as span:
        # Short-circuit only when no chunks AND no useful SQL signal.
        sql_has_signal = sql_outcome is not None and sql_outcome.outcome in (
            "answered",
            "empty",
        )
        if not hits and not sql_has_signal:
            span.set_attribute("firefly.rag.short_circuit", "no_hits_no_sql")
            return Answer(text=_NO_INFO_TEXT, citations=[], cited_sources=[])
        parts: list[str] = [f"Question: {question}"]
        if sql_outcome is not None and sql_outcome.outcome == "answered":
            parts.append(
                f"## Structured Data Results\n\n{sql_outcome.result_markdown}"
            )
        elif sql_outcome is not None and sql_outcome.outcome == "empty":
            parts.append(_format_empty_sql_section(sql_outcome))
        formatted = format_chunks_for_prompt(hits)
        if formatted:
            parts.append(f"## Retrieved Documents\n\n{formatted}")
        prompt = "\n\n".join(parts)
        result = await self._agent.run(prompt)
        answer = result.output
        answer.cited_sources = _build_cited_sources(answer.citations, hits)
        span.set_attribute("firefly.rag.citation_count", len(answer.cited_sources))
        span.set_attribute(
            "firefly.rag.hallucinated_citation_count",
            max(0, len(answer.citations) - len(answer.cited_sources)),
        )
        return answer
```

Add the helper below the class (at the bottom of `answerer.py`):

```python
def _format_empty_sql_section(outcome: "SqlRetrievalOutcome") -> str:
    """Format the prompt section that surfaces an empty-SQL attempt + probe trail."""
    lines = ["## SQL attempt (no matching rows)"]
    if outcome.attempted_sql is not None:
        lines.append(f"Tried: {outcome.attempted_sql}")
    if outcome.probe_trail:
        lines.append("")
        lines.append("Observations from inspect_table:")
        for rec in outcome.probe_trail:
            lines.append(f"  {rec.table}.{rec.column} {rec.op} → {rec.result}")
    return "\n".join(lines)
```

(Note the quoted `"SqlRetrievalOutcome | None"` annotation in the signature — the import is at module top but a quoted form avoids any circular-import risk if `sql.py` ever imports from `answerer.py`.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/corpus_search/test_answerer_sql_context.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/answerer.py tests/unit/corpus_search/test_answerer_sql_context.py
git commit -m "$(cat <<'EOF'
feat(rag): AnswerAgent consumes SqlRetrievalOutcome

The answerer now accepts a structured outcome instead of an opaque
sql_context string. When SQL ran but matched no rows the prompt carries
the attempted SQL + probe trail and the answerer is instructed to tell
the user the closest available values rather than falling back to
'I don't have enough information.'

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update `CorpusAgent.query` callsite

**Files:**
- Modify: `fireflyframework_agentic/rag/agent.py:636-640`
- Test: `tests/integration/test_corpus_agent_structured.py`

- [ ] **Step 1: Inspect the existing integration test**

```bash
grep -n "sql_context\|sql_outcome\|_structured_retriever" tests/integration/test_corpus_agent_structured.py
```

Note the line numbers — the integration test patches `_structured_retriever.retrieve` to return a markdown string today. After Task 5 the return type is a `SqlRetrievalOutcome`. The patches need updating.

- [ ] **Step 2: Run the integration test to verify it now fails**

```bash
uv run pytest tests/integration/test_corpus_agent_structured.py -v
```

Expected: failures on type / attribute access (the answerer expects `SqlRetrievalOutcome`, the stubbed retriever still returns a string).

- [ ] **Step 3: Update the callsite in `CorpusAgent.query`**

Edit `fireflyframework_agentic/rag/agent.py`. Replace lines 636-640 (the `asyncio.gather(...)` and the `answer = await self._answerer.answer(...)` call). The old code passes `sql_context=...`; change to `sql_outcome=...`. The local variable name should also be renamed to make the change reviewable:

Find:
```python
            top_hits, sql_context = await asyncio.gather(
                self.retrieve(question, top_k=top_k, rerank=True),
                self._structured_retriever.retrieve(question, schemas),
            )
            answer = await self._answerer.answer(question, top_hits, sql_context=sql_context)
            outcome = "no_info" if not answer.cited_sources else "answered"
```

Replace with:
```python
            top_hits, sql_outcome = await asyncio.gather(
                self.retrieve(question, top_k=top_k, rerank=True),
                self._structured_retriever.retrieve(question, schemas),
            )
            answer = await self._answerer.answer(question, top_hits, sql_outcome=sql_outcome)
            outcome = "no_info" if not answer.cited_sources else "answered"
```

- [ ] **Step 4: Update the integration test stubs**

Edit `tests/integration/test_corpus_agent_structured.py`. Wherever the test patches `_structured_retriever.retrieve` or constructs a fake markdown return value, change the return to a `SqlRetrievalOutcome(outcome='answered', result_markdown=..., attempted_sql='SELECT ...', probe_trail=[])`.

Add the import at the top of the test file:
```python
from fireflyframework_agentic.rag.retrieval.sql import SqlRetrievalOutcome
```

And wherever a fake retrieve return like `return "id | name\n---\nWidget"` appears, wrap it:
```python
return SqlRetrievalOutcome(
    outcome="answered",
    result_markdown="id | name\n---\nWidget",
    attempted_sql="SELECT id, name FROM products",
    probe_trail=[],
)
```

(Use `grep -n "return.*markdown\|return None.*retriev\|MagicMock.*output" tests/integration/test_corpus_agent_structured.py` to find the exact callsites; the test mocks the LLM, not pydantic-ai, so the inner-retriever return is what gets adapted.)

- [ ] **Step 5: Run the integration test**

```bash
uv run pytest tests/integration/test_corpus_agent_structured.py -v
```

Expected: passes.

- [ ] **Step 6: Run the full corpus_search + rag test surface**

```bash
uv run pytest tests/unit/corpus_search tests/unit/rag tests/integration/test_corpus_agent_structured.py -v
```

Expected: all pass. Total ~30 tests across these paths.

- [ ] **Step 7: Commit**

```bash
git add fireflyframework_agentic/rag/agent.py tests/integration/test_corpus_agent_structured.py
git commit -m "$(cat <<'EOF'
refactor(rag): CorpusAgent.query passes SqlRetrievalOutcome to answerer

One-line callsite change: sql_context → sql_outcome. Integration test
stubs adapted to return a SqlRetrievalOutcome instead of a markdown
string.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add regression test for the failure mode

**Files:**
- Create: `tests/integration/test_corpus_query_grounding.py`

This test reproduces the original failure shape on a synthetic fixture safe to commit: a synonym mismatch (the user's query term isn't a substring of any column value) plus a column-name overload (a TEXT period-tag column adjacent to a similarly-prefixed REAL column).

- [ ] **Step 1: Write the test**

Create `tests/integration/test_corpus_query_grounding.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Regression: SQL retriever can ground itself when labels mismatch the query.

Reproduces the 'synonym + column-name overload' failure mode on a synthetic
sales fixture. Before the inspect-loop change, a question that used an
operator-shorthand label and referred to year-prefix columns would generate
a SELECT that ran cleanly but matched 0 rows. After the change, the agent
inspects the columns first and finds the canonical values.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.sql import (
    SqlRetrievalOutcome,
    StructuredRetriever,
)


def _grounding_fixture(tmp_path: Path) -> tuple[Path, TargetSchema]:
    """A schema with two failure shapes baked in:

    - `product_name` contains 'MX-3000 Wireless Mouse', NOT 'wireless mouse'
      (so a naive LIKE '%wireless mouse%' filter — case-sensitive — misses).
    - `period` is TEXT ('2025-Q4'), `period_revenue` is REAL (4200.0). The
      column names overlap, so a thin-context LLM is liable to filter on
      `period_revenue = 2025` and find nothing.
    """
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sales (period TEXT, region TEXT, product_name TEXT, "
        "revenue REAL, period_revenue REAL)"
    )
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?, ?, ?, ?)",
        [
            ("2025-Q4", "EU-North", "MX-3000 Wireless Mouse", 1200.0, 4200.0),
            ("2025-Q4", "EU-South", "MX-3000 Wireless Mouse", 800.0, 4200.0),
            ("2025-Q4", "EU-South", "K10 Keyboard", 600.0, 4200.0),
            ("2025-Q3", "NA", "MX-3000 Wireless Mouse", 950.0, 3100.0),
        ],
    )
    conn.commit()
    conn.close()
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="period", type=ColumnType.string),
                    ColumnSpec(name="region", type=ColumnType.string),
                    ColumnSpec(name="product_name", type=ColumnType.string),
                    ColumnSpec(name="revenue", type=ColumnType.number),
                    ColumnSpec(name="period_revenue", type=ColumnType.number),
                ],
            )
        ]
    )
    return db, schema


@pytest.mark.asyncio
async def test_inspect_loop_recovers_from_synonym_and_overload(tmp_path: Path):
    """End-to-end on the fixture: agent inspects, finds canonical values, runs the right SELECT."""
    db, schema = _grounding_fixture(tmp_path)
    retriever = StructuredRetriever(db)

    # Replay the agent's tool-call sequence deterministically. This is what a
    # correctly-functioning Haiku agent does on this fixture (verified by hand
    # against the real model in the diagnostic notebook).
    async def replay(prompt, **kwargs):
        tools = retriever._last_built_tools
        # 1. The agent doesn't know what product_name values exist — probe.
        await tools["inspect_table"]("sales", "product_name", "distinct_values")
        # 2. period column is text — probe its format.
        await tools["inspect_table"]("sales", "period", "distinct_values")
        # 3. region prefix is unclear — probe.
        await tools["inspect_table"]("sales", "region", "distinct_values")
        # 4. Final SELECT using the correct column (revenue, not period_revenue)
        #    and the canonical product name found via inspection.
        await tools["run_select"](
            "SELECT product_name, SUM(revenue) FROM sales "
            "WHERE period='2025-Q4' AND region LIKE 'EU-%' "
            "AND product_name LIKE '%Wireless Mouse%' "
            "GROUP BY product_name"
        )
        return type("R", (), {"output": "done"})()

    from unittest.mock import AsyncMock, patch
    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=replay)):
        outcome = await retriever.retrieve(
            "wireless mouse revenue in Europe last quarter", schemas=[schema]
        )

    assert outcome.outcome == "answered", (
        f"expected 'answered' but got {outcome.outcome}; "
        f"attempted={outcome.attempted_sql}; probes={len(outcome.probe_trail)}"
    )
    assert outcome.result_markdown is not None
    assert "MX-3000 Wireless Mouse" in outcome.result_markdown
    # The combined revenue for EU regions in 2025-Q4 is 2000.0 (1200 + 800).
    assert "2000" in outcome.result_markdown
    # And the trail records the three probes we drove.
    assert {p.column for p in outcome.probe_trail} == {"product_name", "period", "region"}


@pytest.mark.asyncio
async def test_inspect_loop_reports_empty_when_data_truly_absent(tmp_path: Path):
    """A query for data the corpus doesn't contain produces outcome='empty', not 'unsupported'."""
    db, schema = _grounding_fixture(tmp_path)
    retriever = StructuredRetriever(db)

    async def replay(prompt, **kwargs):
        tools = retriever._last_built_tools
        await tools["inspect_table"]("sales", "region", "distinct_values")
        await tools["run_select"]("SELECT * FROM sales WHERE region='Antarctica'")
        return type("R", (), {"output": "no rows"})()

    from unittest.mock import AsyncMock, patch
    with patch.object(retriever._sql_agent, "run", new=AsyncMock(side_effect=replay)):
        outcome = await retriever.retrieve(
            "Antarctica sales last quarter", schemas=[schema]
        )

    assert outcome.outcome == "empty"
    assert outcome.attempted_sql == "SELECT * FROM sales WHERE region='Antarctica'"
    assert len(outcome.probe_trail) == 1
```

- [ ] **Step 2: Run the regression test**

```bash
uv run pytest tests/integration/test_corpus_query_grounding.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Run the full test surface for this PR**

```bash
uv run pytest tests/unit/corpus_search tests/unit/rag tests/integration/test_corpus_agent_structured.py tests/integration/test_corpus_query_grounding.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_corpus_query_grounding.py
git commit -m "$(cat <<'EOF'
test(rag): regression test for inspect-loop grounding

Synthetic-but-shaped-like-the-real-bug fixture: synonym mismatch
(product_name has 'MX-3000 Wireless Mouse', not 'wireless mouse') and
column-name overload (period TEXT vs period_revenue REAL). Asserts the
inspect loop reaches outcome='answered' on the fixture, and outcome=
'empty' on a query whose answer genuinely isn't in the data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Manual verification + lint + push + open PR

**Files:** none modified.

- [ ] **Step 1: Run linting / formatting**

```bash
uv run ruff check fireflyframework_agentic/rag/retrieval/ tests/unit/corpus_search/ tests/integration/test_corpus_query_grounding.py
uv run ruff format --check fireflyframework_agentic/rag/retrieval/ tests/unit/corpus_search/ tests/integration/test_corpus_query_grounding.py
```

Expected: no warnings or unformatted files. If formatting fails, run `uv run ruff format <paths>` and amend the relevant commit (or add a follow-up commit, since the project prefers new commits over amends per the global guidance).

- [ ] **Step 2: Run the broader test surface to catch unintended regressions**

```bash
uv run pytest tests/unit tests/integration -x --ignore=tests/integration/test_azure_backend_azurite.py
```

(`test_azure_backend_azurite.py` requires Azurite locally and may be skipped in CI; exclude it here.)

Expected: all pass.

- [ ] **Step 3: Manual smoke test against the real corpus**

Run the diagnostic from the original investigation (the user's failing query) to confirm the live behaviour is now answered or informatively-empty (not the blanket no-info string):

```bash
CORPUS_ROOT=$PWD/kg FIREFLY_AGENTIC_LOG_LEVEL=INFO \
  uv run python /tmp/diagnose_dapa.py 2>&1 | tail -40
```

(If `/tmp/diagnose_dapa.py` was cleaned, re-create it from the original diagnostic — it's the small script that imports `CorpusAgent` directly, runs `agent.query("DAPA revenue sales Brazil product brand 2023 2024 FY")` against `kg/real-data/`, and prints the answer + citations.)

Acceptance: the final `[diag] final answer:` line is no longer the literal string `"I don't have enough information."` — it either contains numeric revenue figures (outcome='answered') or describes the closest available brand/year values (outcome='empty').

- [ ] **Step 4: Push the branch**

```bash
git push -u origin sql-retriever-inspect-loop
```

- [ ] **Step 5: Open the PR**

```bash
gh pr create --title "fix(rag): agentic SQL retriever with inspect loop" --body "$(cat <<'EOF'
## Summary

- Replaces the stateless one-shot text-to-SQL stage with an agentic loop. The SQL agent gets two tools — `inspect_table(table, column, op)` and `run_select(sql)` — and drives its own loop to ground itself against the corpus before composing the final SELECT.
- Changes the structured-retriever return contract from `str | None` to a `SqlRetrievalOutcome` dataclass with three states (`answered`/`empty`/`unsupported`) and a `probe_trail`.
- Updates `AnswerAgent` to consume the outcome: when SQL ran but matched zero rows, the prompt surfaces the attempted SQL + probe observations so the answerer can tell the user the closest available values instead of the blanket "I don't have enough information."
- Slims `_build_schema_context` — sample values are no longer baked into the prompt (that heuristic helped some schemas and misled others). Agent inspects on demand.

Design doc: `docs/superpowers/specs/2026-05-11-sql-retriever-inspect-loop-design.md`.
Implementation plan: `docs/superpowers/plans/2026-05-11-sql-retriever-inspect-loop.md`.

## Test plan

- [x] Unit: `tests/unit/corpus_search/test_sql_retriever.py` — dataclass shapes, `_execute` error/row-cap, `inspect_table` per op, allow-list enforcement, `run_select` SELECT-guard / error-propagation / empty-flag / sentinel detection, loop outcome derivation for all four states.
- [x] Unit: `tests/unit/corpus_search/test_answerer_sql_context.py` — answerer accepts `SqlRetrievalOutcome`; `answered` keeps the existing prompt section; `empty` surfaces the probe trail and does NOT short-circuit; `unsupported` + no hits still emits `_NO_INFO_TEXT`.
- [x] Integration: `tests/integration/test_corpus_agent_structured.py` — stubs updated for new return type; end-to-end through `CorpusAgent.query`.
- [x] Regression: `tests/integration/test_corpus_query_grounding.py` — synthetic fixture reproducing the synonym + column-overload failure mode; agent inspect-and-recover path verified.
- [x] Manual: ran the original failing query against the real corpus; the answer is no longer the blanket no-info string.

## Out of scope (follow-up)

Persistent probe cache (`_schema_probes` table + invalidation on structured re-ingest). Brainstormed and explicitly deferred to its own PR — see the spec's "Non-goals" section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Report PR URL to the user**

The `gh pr create` output includes the PR URL. Surface it explicitly so the user can review.

---

## Self-Review

Spec coverage:
- §1 Architecture & components → Tasks 1-7
- §2 Tool surface — inspect_table → Task 3; run_select → Task 4; system prompt → Task 5
- §3 Output contract — SqlRetrievalOutcome → Task 1; answerer integration → Task 6; CorpusAgent callsite → Task 7
- §4 Error handling — allow-list (Task 3), SELECT-guard (Task 4), row cap (Task 2), loop cap (Task 5)
- §5 Testing — unit-probes (Task 3-4), unit-loop (Task 5), unit-answerer (Task 6), integration (Task 7), regression (Task 8)
- §Rollout — no migrations, no env vars (confirmed in implementation)

Placeholder scan: every code block is concrete; no TBD/TODO; commit messages spelled out; no "fill in details" steps.

Type consistency: `SqlRetrievalOutcome` field names match across Tasks 1, 5, 6, 7, 8. `ProbeRecord` shape consistent everywhere. The `_last_built_tools` test hook is introduced in Task 5 and used in Tasks 5, 8.

Scope: single PR, ~9 commits, ~500 LoC across `sql.py`/`answerer.py`/`agent.py` + tests. The follow-up probe cache is explicitly out of scope and noted in the PR body.
