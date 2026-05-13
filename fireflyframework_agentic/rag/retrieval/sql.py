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

"""Text-to-SQL retriever for structured data ingested into corpus.sqlite."""

from __future__ import annotations

import contextvars
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.usage import UsageLimits

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.rag.ingest.structured_schema import ColumnType, TargetSchema

log = logging.getLogger(__name__)

# Shared heading for the empty-SQL prompt section. The answerer's instructions
# reference this literal to gate the 'don't say I-don't-have-enough-info'
# behaviour, so the two must stay in sync.
EMPTY_SQL_HEADING = "## SQL attempt (no matching rows)"


@dataclass(slots=True, frozen=True)
class ProbeRecord:
    """Record of a single ``inspect_table`` tool call.

    ``result`` is the markdown string the tool returned to the LLM, truncated
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
      - ``answered``: ``run_select`` returned >=1 row. ``result_markdown`` is
        the markdown table; ``attempted_sql`` is the SELECT that produced it.
      - ``empty``: ``run_select`` ran cleanly but returned 0 rows on the last
        attempt. ``result_markdown=None``; ``attempted_sql`` is the last
        SELECT; ``probe_trail`` records what the LLM inspected.
      - ``unsupported``: cap exhausted, sentinel ``SELECT 1 WHERE 1=0``, every
        attempt errored, or ``schemas`` was empty.
    """

    outcome: Literal["answered", "empty", "unsupported"]
    result_markdown: str | None
    attempted_sql: str | None
    probe_trail: list[ProbeRecord] = field(default_factory=list)


MAX_ROWS_IN_RESULT = 100
MAX_ROWS_PER_PROBE = 20


def _unaccent_lower(value: str | None) -> str | None:
    """Strip combining diacritics and lowercase ``value``.

    Registered as a SQLite UDF on every connection (see :func:`_connect`).
    Lets ``unaccent_lower(col) LIKE '%alvarez%'`` match rows that contain
    ``Álvarez`` portably, without needing the SQLite ICU extension. The
    function is pure and deterministic — safe to register with the
    ``deterministic=True`` flag.
    """
    if value is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).lower()


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the framework's SQL UDFs registered."""
    conn = sqlite3.connect(db_path)
    conn.create_function("unaccent_lower", 1, _unaccent_lower, deterministic=True)
    return conn


@dataclass(slots=True)
class _LoopContext:
    """Mutable per-query state shared between the loop tools.

    Built fresh on each :meth:`StructuredRetriever.retrieve` call. Tools close
    over this object; the loop driver reads its final state to build the
    :class:`SqlRetrievalOutcome`.
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


def _build_inspect_tool(ctx: _LoopContext) -> Any:
    """Return an async ``inspect_table(table, column, op)`` tool bound to *ctx*.

    The tool runs parametric SQL — table/column are validated against the
    schema allow-list and quoted; ``op`` selects one of four fixed queries.
    The LLM never composes SQL at inspect time, so injection risk is zero
    by construction.
    """

    allowed = _allowed_columns(ctx.schemas)

    async def inspect_table(
        table: str,
        column: str,
        op: Literal["distinct_values", "count", "sample_rows", "value_range", "find_similar", "numeric_summary"],
        value: str | None = None,
    ) -> str:
        """Peek at the corpus DB before composing the final SELECT.

        Ops:
          - ``distinct_values``: up to MAX_ROWS_PER_PROBE distinct values of *column*
          - ``count``: COUNT(*) of *table*
          - ``sample_rows``: first 5 rows of *table*
          - ``value_range``: MIN/MAX of *column*
          - ``find_similar``: case-insensitive, accent-folded substring match
            against the literal *value*. The value is tokenised on whitespace
            and matched as AND-of-LIKEs (so ``"Javier Alvarez"`` matches
            ``"Francisco Javier Álvarez Fernández"``). Falls back to OR-of-
            tokens if AND yields zero matches. Use this for free-text filters
            on names / entities where the user's spelling may not be exact.
          - ``numeric_summary``: total rows, non-null count, null count, sum,
            min, max, and *two* mean variants: ``mean_excluding_nulls`` (the
            SQL default ``AVG``) and ``mean_blanks_as_zero`` (treats NULL
            cells as 0). Use this before averaging any numeric column where
            blank source cells might be the analyst's shorthand for zero —
            the two means diverge whenever the column carries NULLs, and the
            correct interpretation depends on what blank meant in the source
            spreadsheet.

        Raises :class:`pydantic_ai.exceptions.ModelRetry` if *table* or *column*
        is not in the registered schemas — pydantic-ai surfaces the message
        back to the LLM as a tool error so it can pick a valid name and retry,
        rather than terminating the loop on a typo.
        """
        if table not in allowed:
            raise ModelRetry(f"table '{table}' not in registered schemas; available tables: {sorted(allowed)}")
        cols = allowed[table]
        if op != "count" and column not in cols:
            raise ModelRetry(f"column '{column}' not in '{table}'; available: {sorted(cols)}")
        # Identifier quoting: sqlite uses "..." for identifiers; double up any
        # embedded quote chars. Allow-list already gates non-existent names,
        # so this is belt-and-braces.
        t = '"' + table.replace('"', '""') + '"'
        c = '"' + column.replace('"', '""') + '"'
        params: list[Any] = []
        if op == "distinct_values":
            sql = f"SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT {MAX_ROWS_PER_PROBE}"
        elif op == "count":
            sql = f"SELECT COUNT(*) FROM {t}"
        elif op == "sample_rows":
            sql = f"SELECT * FROM {t} LIMIT 5"
        elif op == "value_range":
            sql = f"SELECT MIN({c}), MAX({c}) FROM {t}"
        elif op == "find_similar":
            if not value or not value.strip():
                raise ModelRetry("find_similar requires a non-empty 'value' argument")
            tokens = [tok for tok in re.split(r"\s+", value.strip()) if tok]
            sql, params = _build_find_similar_sql(t, c, tokens)
        elif op == "numeric_summary":
            result = _numeric_summary(ctx.db_path, t, c)
            ctx.probe_trail.append(ProbeRecord(table=table, column=column, op=op, result=result[:500]))
            return result
        else:
            raise ValueError(f"unknown op '{op}'")
        result = _execute(ctx.db_path, sql, params) or "(no rows)"
        if op == "find_similar" and result == "(no rows)" and len(params) > 1:
            # Relax AND → OR so the LLM sees what's nearby even if no single
            # value contains every token.
            sql, params = _build_find_similar_sql(t, c, tokens, combinator="OR")
            result = _execute(ctx.db_path, sql, params) or "(no rows)"
        ctx.probe_trail.append(ProbeRecord(table=table, column=column, op=op, result=result[:500]))
        return result

    return inspect_table


def _numeric_summary(db_path: Path, quoted_table: str, quoted_column: str) -> str:
    """Return a single-line summary exposing both AVG interpretations.

    SQLite's ``AVG`` quietly skips NULLs; when a source spreadsheet
    encodes "zero" as a blank cell, this turns a population mean into a
    mean over only the non-blank subset. The two values in the returned
    string make that gap explicit so the agent can pick the
    interpretation that matches the analyst's data convention.

    Output shape (single line, key=value pairs):
      ``rows=N non_null=K nulls=M sum=S min=mn max=mx
        mean_excluding_nulls=… mean_blanks_as_zero=…``

    ``mean_excluding_nulls`` is reported as ``undefined`` when every
    cell is NULL (SQL ``AVG`` returns NULL in that case and there is no
    meaningful population mean to report).
    """
    sql = (
        f"SELECT COUNT(*), COUNT({quoted_column}), "
        f"COALESCE(SUM({quoted_column}), 0), "
        f"MIN({quoted_column}), MAX({quoted_column}), "
        f"AVG({quoted_column}) "
        f"FROM {quoted_table}"
    )
    try:
        with _connect(db_path) as conn:
            row = conn.execute(sql).fetchone()
    except sqlite3.Error as exc:
        log.warning("numeric_summary execution failed: %s", exc)
        return f"SQL error: {exc}"
    total, non_null, total_sum, min_v, max_v, mean_excl = row
    nulls = total - non_null
    # Population mean treating blanks as 0; safe because total > 0 when the
    # table is non-empty, and we report "rows=0" plainly when it is.
    mean_pop = (total_sum / total) if total else 0.0
    mean_excl_str = "undefined" if mean_excl is None else _fmt_float(float(mean_excl))
    parts = [
        f"rows={total}",
        f"non_null={non_null}",
        f"nulls={nulls}",
        f"sum={_fmt_number(total_sum)}",
        f"min={_fmt_number(min_v) if min_v is not None else 'null'}",
        f"max={_fmt_number(max_v) if max_v is not None else 'null'}",
        f"mean_excluding_nulls={mean_excl_str}",
        f"mean_blanks_as_zero={_fmt_float(mean_pop)}",
    ]
    return " ".join(parts)


def _fmt_number(value: Any) -> str:
    """Format ints as ints and floats compactly — keeps the summary readable."""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _fmt_float(value)
    return str(value)


def _fmt_float(value: float) -> str:
    """Stable float formatting: drop trailing zeros but keep at least one decimal.

    ``4.0`` stays as ``"4.0"`` (distinguishing it from int 4 in the output)
    and ``1.333333…`` becomes ``"1.3333"`` — enough precision to make the
    blanks-vs-zero gap visible without dumping IEEE noise.
    """
    if value == int(value):
        return f"{value:.1f}"
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0.0"


def _build_find_similar_sql(
    quoted_table: str,
    quoted_column: str,
    tokens: list[str],
    *,
    combinator: str = "AND",
) -> tuple[str, list[Any]]:
    """Build the parametric SQL for ``find_similar``.

    All tokens are accent-folded + lowercased before binding, and matched
    against ``unaccent_lower(column)`` on the row side. ``combinator`` is
    ``"AND"`` for the strict pass and ``"OR"`` for the relaxed fallback.
    """
    if not tokens:
        # Defensive: the caller validates non-empty input, but guard against
        # a future caller skipping that check.
        return ("SELECT NULL WHERE 0=1", [])
    predicates = f" {combinator} ".join([f"unaccent_lower({quoted_column}) LIKE ?"] * len(tokens))
    sql = (
        f"SELECT DISTINCT {quoted_column} FROM {quoted_table} "
        f"WHERE {quoted_column} IS NOT NULL AND ({predicates}) "
        f"LIMIT {MAX_ROWS_PER_PROBE}"
    )
    params: list[Any] = [f"%{_unaccent_lower(tok)}%" for tok in tokens]
    return sql, params


def _build_run_select_tool(ctx: _LoopContext) -> Any:
    """Return an async ``run_select(sql)`` tool bound to *ctx*.

    Each call updates ``ctx.attempted_sql`` and ``ctx.last_result_*`` so the
    loop driver can read the terminal state when the agent stops.
    """

    async def run_select(sql: str) -> str:
        """Execute the final SELECT statement against the corpus DB.

        - Must start with SELECT (case-insensitive, leading whitespace
          allowed). Returns ``'SQL must start with SELECT.'`` on violation —
          the LLM can revise and retry.
        - Returns ``'SQL error: ...'`` on sqlite3 errors so the LLM can self-
          correct (the loop is not terminated on a single error).
        - Returns ``'Query returned 0 rows.'`` on a clean run with no matches —
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


_SYSTEM = """\
You answer questions by querying a SQLite corpus database. You have two tools:

  inspect_table(table, column, op, value=None)
    op = 'distinct_values' | 'count' | 'sample_rows' | 'value_range'
       | 'find_similar' | 'numeric_summary'
    Use this to discover what values a column actually contains BEFORE you
    write the final SELECT. Free — call it whenever you are not sure.

    'find_similar' takes an extra `value` argument and returns column
    values that match the value case-insensitively and accent-folded,
    tokenised by whitespace (AND across tokens). Use it for free-text
    filters on names / entities where the user's spelling may differ
    from what is stored (e.g. accents, middle names, abbreviations).

    'numeric_summary' returns row count, non-null count, null count, sum,
    min, max, AND two mean variants for the column:
      - mean_excluding_nulls  (SQL default AVG; ignores NULL cells)
      - mean_blanks_as_zero   (treats NULL cells as 0 in the average)
    The two diverge whenever the column has NULLs. Use it BEFORE you
    write an aggregate query that averages a numeric column, and look at
    nulls > 0 as the signal that you need to choose between the two
    interpretations.

  run_select(sql)
    Use this to run your final SELECT once you are confident in the values.
    You may call it more than once if the result was empty or errored.
    The helper SQL function `unaccent_lower(col)` is available — prefer
    `unaccent_lower(col) LIKE '%token%'` over `col = 'literal'` when
    filtering on person names or other free-text fields, so accents,
    case, and partial overlaps match.

Reading the schema:
  Each string column below is annotated with its distinct-value count,
  e.g. `metric_line (string, 3 distinct)`. A low count (typically <50)
  flags a categorical / discriminator axis — a column you may need to
  filter on with WHERE before aggregating other columns in the same
  table. A count near the row count signals a unique identifier. Use
  these counts to decide where filters and GROUP BY clauses belong.

Process:
  1. Read the schema below.
  2. If you are NOT sure what values exist in the columns you want to filter
     on, call inspect_table first.
     - For free-text identifiers (person names, product names, locations
       whose stored form may differ from the user's wording) use
       `find_similar` with the user's literal string.
     - For closed-set columns (regions, categories, status flags) use
       `distinct_values`.
     - Don't probe columns whose values are obvious from the question.
  3. Call run_select with your final SELECT.
  4. If run_select returns 'Query returned 0 rows.' on an equality filter
     for a string column, do NOT stop. Probe `find_similar` on that column
     with the original value first — there is usually a near match (different
     accents, middle names, casing). Retry the SELECT against the candidates
     you find. Aim for at most 3 inspect calls without making progress.
  5. If run_select returns 'SQL error: ...', revise and retry.
  6. Before averaging a numeric column over a population (e.g. an
     average across all rows in a team / group), call `numeric_summary`
     on that column. If `nulls > 0`, blank cells exist and you must
     decide whether the analyst's convention is "blank = no data"
     (use `mean_excluding_nulls`, i.e. plain AVG) or "blank = zero"
     (use `mean_blanks_as_zero`, i.e. `AVG(COALESCE(col, 0))` or
     `SUM(col)/COUNT(*)`). When in doubt, surface both interpretations
     in your answer.
  7. Before SUM / AVG / COUNT over a numeric column, scan the same
     table's string columns. Any string column with a low distinct
     count (roughly 3–50) — especially names like `*_line`, `*_type`,
     `*_category`, `kpi`, `metric` — is almost certainly a
     discriminator that mixes heterogeneous concepts in the value
     column. Call `distinct_values` on it and add a WHERE filter
     before aggregating, or your sum will combine apples with oranges.
  8. If the question contains "by X", "for each X", "per X", or
     "across X", use `GROUP BY X` with the aggregate over the metric
     column — not a flat `SELECT *`. Use the distinct counts in the
     schema annotation to confirm you're grouping at the level the
     user asked for: a parent column has a lower distinct count than
     a child column inside the same table.
  9. If `run_select` returns 0 rows on a single-column lookup, or
     returns NULL for the column you queried, do NOT immediately
     conclude "no record." Scan the table's other columns: any
     column whose name shares semantic tokens with the question
     (e.g. the question asks about "structural change" and the
     table has `role_change`, `recorded_movement`,
     `effective_date_of_route_change`) is a candidate. Re-run
     `run_select` selecting all the candidate columns before
     answering. Only conclude "no record" once every semantically
     relevant column has been probed.

Worked example 1 (illustrative; no real corpus):
  Question: "wireless mouse sales in Europe last quarter"
  Schema: sales (period string, product_name string, region string,
                 revenue number, ...)
  Reasoning: "wireless mouse" might be a category label or a specific
             product. "Europe" might be a single region value or a prefix
             on several. Inspect both.

  inspect_table(sales, product_name, 'distinct_values')
    -> ['MX-3000 Wireless Mouse', 'MX-3000 Pro', 'K10 Keyboard', ...]
  inspect_table(sales, region, 'distinct_values')
    -> ['EU-North', 'EU-South', 'NA', 'APAC']
  run_select("SELECT product_name, SUM(revenue) FROM sales "
             "WHERE period='2025-Q4' AND region LIKE 'EU-%' "
             "AND unaccent_lower(product_name) LIKE '%wireless mouse%' "
             "GROUP BY product_name")

Worked example 2 (ambiguous person name):
  Question: "Who is Javier Alvarez's manager?"
  Schema: employees (id int, name string, manager_id int, ...)
  Reasoning: stored names may carry accents and middle names; the user's
             string almost certainly is not the literal full name.

  inspect_table(employees, name, 'find_similar', value='Javier Alvarez')
    -> ['Francisco Javier Álvarez Fernández', 'María Álvarez', ...]
  run_select("SELECT name, manager_id FROM employees "
             "WHERE name = 'Francisco Javier Álvarez Fernández'")

  If find_similar returns multiple candidates and the question does not
  pick one, return rows for all candidates (WHERE name IN (...)) so the
  caller can disambiguate. Do NOT silently pick one.

Worked example 3 (discriminator filter — aggregating across categories):
  Question: "What is the 2024 revenue for market EU?"
  Schema: finance_fact: year (string, 5 distinct), market (string, 12 distinct),
                        metric_line (string, 3 distinct), value (float)
  Reasoning: metric_line has only 3 distinct values — almost certainly
             a categorical discriminator. SUM(value) without filtering
             on it would mix revenue, headcount, and expense into one
             meaningless number.

  inspect_table(finance_fact, metric_line, 'distinct_values')
    -> ['Total Revenue', 'Active Headcount', 'Operating Expense']
  run_select("SELECT SUM(value) FROM finance_fact "
             "WHERE year='2024' AND market='EU' "
             "AND metric_line='Total Revenue'")

Worked example 4 (GROUP BY at parent level — "by X" phrasings):
  Question: "What is the average achievement by business_unit?"
  Schema: performance: team_id (integer), team_name (string, 4 distinct),
                       business_unit (string, 2 distinct), achievement_pct (float)
  Reasoning: "by business_unit" → GROUP BY business_unit. The 2:4 ratio
             between business_unit (2 distinct) and team_name (4 distinct)
             confirms the parent/child hierarchy — one BU has multiple
             teams. The user wants one row per BU, not per team.

  run_select("SELECT business_unit, AVG(achievement_pct) "
             "FROM performance GROUP BY business_unit")

Worked example 5 (sibling-column scan — don't stop at the first NULL):
  Question: "Has there been any structural change for employee 42?"
  Schema: employee_changes: employee_id (integer), name (string, 1000 distinct),
                            recorded_movement (string, 8 distinct),
                            effective_date_of_route_change (string, 12 distinct),
                            role_change (string, 6 distinct)
  Reasoning: `recorded_movement` is the most literal column, but
             `effective_date_of_route_change` and `role_change` also
             carry the semantic concept of "structural change."
             Check all three before answering.

  run_select("SELECT recorded_movement FROM employee_changes "
             "WHERE employee_id=42")
    -> recorded_movement = NULL
  run_select("SELECT recorded_movement, effective_date_of_route_change, role_change "
             "FROM employee_changes WHERE employee_id=42")
    -> effective_date_of_route_change='2024-07-01', role_change='New region'

Rules:
  - SELECT only. No INSERT/UPDATE/DELETE/DROP/ALTER. The run_select tool
    enforces this; non-SELECT statements are rejected.
  - Use the exact table and column names from the schema below.
  - If the question cannot be answered from this schema at all, call
    run_select('SELECT 1 WHERE 1=0') and stop.
  - When the schema lists a column with `unit=…`, preserve that unit
    in your SELECT result — alias the column to embed it (e.g.
    `SUM(value) AS "total_value_usd_millions"`) or co-select the unit
    literal. Do not silently strip the unit.
"""


_DEFAULT_SQL_MODEL = "anthropic:claude-haiku-4-5-20251001"
_MAX_TOOL_CALLS = 8

# Per-call loop context, scoped via ContextVar so concurrent retrieve() calls
# on the same retriever instance (e.g. when a single CorpusAgent fields two
# in-flight corpus_query requests) don't cross-pollute their probe trails or
# attempted-SQL records. The tool closures registered on _sql_agent read from
# this var; retrieve() sets it within a token scope and resets on exit.
_CURRENT_CTX: contextvars.ContextVar[_LoopContext | None] = contextvars.ContextVar("firefly_sql_loop_ctx", default=None)


class StructuredRetriever:
    """Agentic text-to-SQL retriever.

    Builds a fresh ``_LoopContext`` per query (scoped via :data:`_CURRENT_CTX`),
    exposes ``inspect_table`` and ``run_select`` as tools, and lets the LLM
    drive the loop. The terminal :class:`SqlRetrievalOutcome` is built from
    the context's final state — the agent's natural-language closing message
    is discarded.
    """

    def __init__(self, db_path: Path, *, sql_model: str = _DEFAULT_SQL_MODEL) -> None:
        self._db_path = db_path
        self._sql_model = sql_model

        async def inspect_table(
            table: str,
            column: str,
            op: Literal["distinct_values", "count", "sample_rows", "value_range", "find_similar", "numeric_summary"],
            value: str | None = None,
        ) -> str:
            ctx = _CURRENT_CTX.get()
            assert ctx is not None, "inspect_table called outside retrieve()"
            return await _build_inspect_tool(ctx)(table, column, op, value)

        async def run_select(sql: str) -> str:
            ctx = _CURRENT_CTX.get()
            assert ctx is not None, "run_select called outside retrieve()"
            return await _build_run_select_tool(ctx)(sql)

        # Test hook: tools exposed for deterministic loop replay in unit tests
        # that patch _sql_agent.run. Production callers MUST NOT invoke these
        # directly — the agent does, and a direct call outside retrieve() will
        # trip the `ctx is not None` assertion in each closure.
        self._test_tools: dict[str, Any] = {
            "inspect_table": inspect_table,
            "run_select": run_select,
        }

        self._sql_agent = FireflyAgent(
            name="sql_inspector",
            model=sql_model,
            instructions=_SYSTEM,
            tools=[inspect_table, run_select],
            auto_register=False,
        )

    async def retrieve(
        self,
        question: str,
        schemas: list[TargetSchema],
    ) -> SqlRetrievalOutcome:
        """Run the inspect-and-select loop.

        Returns a :class:`SqlRetrievalOutcome` describing what happened. Never
        raises on tool errors or agent failures — both produce a structured
        outcome built from whatever progress the loop made. If a ``run_select``
        succeeded before a later failure, the ``answered`` state is preserved.
        """
        if not schemas:
            return SqlRetrievalOutcome(
                outcome="unsupported",
                result_markdown=None,
                attempted_sql=None,
                probe_trail=[],
            )
        ctx = _LoopContext(db_path=self._db_path, schemas=schemas)
        prompt = f"{_build_schema_context(schemas, self._db_path)}\n\nQuestion: {question}"
        token = _CURRENT_CTX.set(ctx)
        try:
            await self._sql_agent.run(
                prompt,
                usage_limits=UsageLimits(tool_calls_limit=_MAX_TOOL_CALLS),
            )
        except Exception as exc:
            # Loop terminated abnormally (e.g. UsageLimitExceeded, model error,
            # network blip). Don't discard progress — the context may already
            # carry a successful run_select that we should report as answered.
            log.warning("SQL agent loop failed: %s", exc)
        finally:
            _CURRENT_CTX.reset(token)
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


def _build_schema_context(schemas: list[TargetSchema], db_path: Path | None = None) -> str:
    """Format the table+column listing for the agent's system prompt.

    No sample values: the agent inspects on demand. This avoids the
    heuristic that previously sampled only the first string column —
    which silently misled the LLM on schemas whose first text column was
    an opaque primary key.

    When *db_path* is provided, each string-typed column is annotated
    with its ``COUNT(DISTINCT)`` cardinality (e.g. ``metric_line (string,
    3 distinct)``). The annotation gives the LLM a structural signal:
    low counts (a handful of distinct values) flag categorical /
    discriminator columns that should usually appear in a ``WHERE``
    clause before aggregating other columns in the same table, while a
    count near the row count signals a unique identifier. Cardinality
    failures fall back to the un-annotated descriptor and log a
    warning — schema drift must not block retrieval.

    When ``ColumnSpec.unit`` is set, the unit is also appended (e.g.
    ``value (float, unit=USD millions)``) so the agent echoes the
    correct unit alongside any numeric value it returns. Both
    annotations live inside the same parenthesised, comma-separated
    list — order is ``type, [N distinct,] [unit=…]``.
    """
    cardinalities = _string_column_cardinalities(schemas, db_path) if db_path is not None else {}
    lines: list[str] = ["Available tables:"]
    for schema in schemas:
        for table in schema.tables:
            descs = [_format_column_descriptor(c, cardinalities.get((table.name, c.name))) for c in table.columns]
            lines.append(f"- {table.name}: {', '.join(descs)}")
    return "\n".join(lines)


def _format_column_descriptor(column: Any, distinct: int | None = None) -> str:
    """Render one ``ColumnSpec`` as ``name (type[, N distinct][, unit=…])``.

    Single render path for the agent-facing descriptor. The schema
    context, future error messages, and ad-hoc debug prints share this
    shape, so the worked examples in ``_SYSTEM`` (which copy the format
    literally) stay in lockstep with what the agent actually sees.

    ``distinct`` is appended only when the caller probed cardinality —
    typically only for string columns, and only when a ``db_path`` was
    available. Numeric / date columns always render without a count.
    """
    parts = [column.type.value]
    if distinct is not None:
        parts.append(f"{distinct} distinct")
    if column.unit:
        parts.append(f"unit={column.unit}")
    return f"{column.name} ({', '.join(parts)})"


def _string_column_cardinalities(schemas: list[TargetSchema], db_path: Path) -> dict[tuple[str, str], int]:
    """Return ``{(table, column): distinct_count}`` for every string column.

    Runs one ``COUNT(DISTINCT col)`` per string column on a single
    connection. Per-column failures are logged and silently dropped from
    the result map — :func:`_build_schema_context` then falls back to the
    plain descriptor for those columns. Returns ``{}`` if the connection
    itself cannot be opened.
    """
    out: dict[tuple[str, str], int] = {}
    try:
        conn = _connect(db_path)
    except sqlite3.Error as exc:
        # Don't log db_path itself — CodeQL treats filesystem paths as
        # private data, and matching the file-wide pattern of "log the
        # exception, not the path" keeps us out of that lane.
        log.warning("cardinality probe: could not open db: %s", exc)
        return out
    try:
        for schema in schemas:
            for table in schema.tables:
                quoted_table = '"' + table.name.replace('"', '""') + '"'
                for col in table.columns:
                    if col.type != ColumnType.string:
                        continue
                    quoted_col = '"' + col.name.replace('"', '""') + '"'
                    try:
                        row = conn.execute(f"SELECT COUNT(DISTINCT {quoted_col}) FROM {quoted_table}").fetchone()
                    except sqlite3.Error as exc:
                        log.warning(
                            "cardinality probe failed for %s.%s: %s",
                            table.name,
                            col.name,
                            exc,
                        )
                        continue
                    if row is not None and row[0] is not None:
                        out[(table.name, col.name)] = int(row[0])
    finally:
        conn.close()
    return out


def _execute(db_path: Path, sql: str, params: list[Any] | None = None) -> str | None:
    """Execute *sql* (with optional bound *params*) and return a markdown table.

    Returns:
      - markdown table (possibly with a truncation footer) on success with rows
      - None if the SELECT ran successfully but matched 0 rows
      - a human-readable message starting with ``SQL error:`` on failure

    The 'error string vs None vs table' distinction lets the caller decide what
    state to record on the outcome: an error means the LLM should retry; None
    means the caller marks ``outcome='empty'``; a table means ``outcome=
    'answered'``.
    """
    try:
        with _connect(db_path) as conn:
            cur = conn.execute(sql, params or [])
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
