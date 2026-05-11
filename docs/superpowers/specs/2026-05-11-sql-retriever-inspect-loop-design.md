# Design: Agentic SQL Retriever with Inspect Loop

**Date:** 2026-05-11
**Branch:** `sql-retriever-inspect-loop` → target `main`
**Status:** Draft (awaiting user review)

## Goal

Replace the stateless one-shot text-to-SQL stage in
`fireflyframework_agentic/rag/retrieval/sql.py` with a tool-using agent
loop that can inspect the corpus database before committing to a final
`SELECT`. The agent reports a structured outcome to the answerer, so
queries that ran cleanly but matched zero rows produce a helpful
diagnostic answer instead of the blanket `"I don't have enough
information."` string.

## Why

The current `StructuredRetriever` builds a thin schema-context prompt
(`table.column (type)` plus sample values for the *first string column
only*), asks the LLM for a SELECT, executes it, and returns the
markdown. When the schema is ambiguous — operator-shorthand vs.
canonical brand names, year tags in a TEXT column adjacent to a
similarly-named REAL revenue column, etc. — the LLM has no way to
discover the actual values it needs to filter on. The SELECT executes
successfully, returns zero rows, and the pipeline collapses to a
no-info answer that hides the fact that the data is present in the
corpus.

The narrower fixes considered (sampling more text columns, adding a
`ColumnSpec.description` field) are heuristic patches. They expand what
the LLM is told upfront but don't help when the operator filters on a
column we didn't think to sample, or when labels are encoded as
synonyms / abbreviations. A tool-using SQL agent generalises across
all of those because it gets to *check* the data before committing.

---

## Decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Loop shape | Agentic tool-use loop (LLM drives, bounded by `max_steps`) |
| 2 | Tool surface | Typed `inspect_table(table, column, op)` + `run_select(sql)` |
| 3 | Output contract | `SqlRetrievalOutcome` dataclass replacing `str \| None` |
| 4 | Budget | Haiku, `max_steps=8`, `max_rows_per_probe=20`, `max_rows_in_result=100` |
| 5 | Probe persistence | Out of scope — separate follow-up PR for `_schema_probes` table + invalidation |

## Non-goals

- Persistent probe cache across queries (see follow-up).
- Changes to schema discovery, `ColumnSpec`, the schema registry, or
  the persisted JSON.
- New env vars or feature flags.
- Multi-statement / DDL support.
- Pagination of result tables larger than `max_rows_in_result`.

---

## Architecture

`StructuredRetriever` flips from stateless one-shot to an agentic
loop. The change is contained to `sql.py`; no new files. The public
callsite (`CorpusAgent.query` calling
`await self._structured_retriever.retrieve(question, schemas)`) keeps
the same shape but the return type changes from `str | None` to
`SqlRetrievalOutcome`. `AnswerAgent.answer` (in `answerer.py`) is
updated to accept and format that outcome.

### Module layout (sql.py)

```
sql.py
  SqlRetrievalOutcome      (frozen dataclass — public)
  ProbeRecord              (frozen dataclass — public)
  _LoopContext             (private — closure state for tools)
  _build_inspect_tool      (private — returns inspect_table closure)
  _build_run_select_tool   (private — returns run_select closure)
  _build_schema_context    (existing — kept, slimmed: no first-string-column sampling)
  StructuredRetriever      (rewired — public)
```

`_build_schema_context` becomes simpler: it no longer tries to fish
out the "first string column" and sample it. Sample values are now
the agent's job. This removes a fragile heuristic that helped some
schemas and misled others.

### Loop overview

```
StructuredRetriever.retrieve(question, schemas)
  │
  ├─ build _LoopContext (db_path, allowed_tables, allowed_columns)
  ├─ build tools: inspect_table, run_select (closures over context)
  ├─ build prompt:
  │     - system: SYSTEM_INSTRUCTIONS (worked example)
  │     - user:   schema_context + question
  │
  ├─ agent.run(prompt, max_steps=8)
  │     ↑ agent makes tool calls; each call appends to probe_trail
  │       or sets last_attempted_sql + last_result_markdown
  │
  └─ build SqlRetrievalOutcome from _LoopContext state
        outcome = 'answered' | 'empty' | 'unsupported'
```

The agent has no structured output type — observable state is captured
via tool-call side effects on `_LoopContext` (probe trail, last SQL,
last result). The `SqlRetrievalOutcome` is built from that state when
the loop terminates (either by the agent stopping naturally or by
hitting `max_steps`).

---

## Tool surface

Both tools are async functions registered with `FireflyAgent` via the
existing `tools=` parameter (`fireflyframework_agentic/agents/base.py:114`).

### `inspect_table`

```python
async def inspect_table(
    table: str,
    column: str,
    op: Literal['distinct_values', 'count', 'sample_rows', 'value_range'],
) -> str:
    """Read a small slice of the corpus DB to ground the final SQL.

    Ops:
      - distinct_values: SELECT DISTINCT "col" FROM "tbl" LIMIT 20
      - count:           SELECT COUNT(*) FROM "tbl"
      - sample_rows:     SELECT * FROM "tbl" LIMIT 5
      - value_range:     SELECT MIN("col"), MAX("col") FROM "tbl"

    Returns a markdown table. Raises ValueError if table/column is not
    in the registered schemas (whitelist enforced — the LLM cannot probe
    `_schemas`, `_ingestions`, `sqlite_master`, etc.).
    """
```

The implementation parametrically builds the query — the LLM never
writes raw SQL at probe time, so injection risk on inspection is zero
by construction. Quoting uses sqlite's `"..."` identifier form; table
and column names are looked up against the allow-list before being
substituted.

### `run_select`

```python
async def run_select(sql: str) -> str:
    """Run the final SELECT against the corpus DB.

    Must start with SELECT (case-insensitive, leading whitespace
    allowed). Returns a markdown table capped at
    MAX_ROWS_IN_RESULT rows. May be called more than once — the LLM
    can revise — but each call counts against max_steps.
    """
```

Reuses the existing `(?i)^\s*SELECT\b` guard and `_execute` helper.
Extends `_execute` to surface sqlite3.Error messages back to the LLM
as the tool's return value (today they are swallowed and the loop
terminates), so the agent can self-correct on SQL errors.

### System prompt

```
You answer questions by querying a SQLite database. Two tools available:

  inspect_table(table, column, op)  — peek at the data before committing.
  run_select(sql)                   — run the final SELECT.

Process:
  1. Read the schema below.
  2. If you are NOT sure what values exist in the columns you want to
     filter on, call inspect_table first. Don't probe columns whose
     values are obvious from the question.
  3. Call run_select with your final SELECT.
  4. If run_select returns 0 rows or an error, you may inspect more and
     retry — but do not exceed 3 inspect calls without making progress.

Worked example (illustrative; no real corpus):
  Question: "wireless mouse sales in Europe last quarter"
  Schema: sales (period string, product_name string, region string, revenue number, ...)
  Reasoning: "wireless mouse" might be a category label or a brand —
             I don't know which. "Europe" might be a single region
             value or a prefix on several. I'll inspect both.

  inspect_table(sales, product_name, distinct_values)
    → ['MX-3000 Wireless Mouse', 'MX-3000 Pro', 'K10 Keyboard', ...]
  inspect_table(sales, region, distinct_values)
    → ['EU-North', 'EU-South', 'NA', 'APAC']
  inspect_table(sales, period, distinct_values)
    → ['2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4']
  run_select(
    "SELECT product_name, SUM(revenue) FROM sales
     WHERE period='2025-Q4' AND region LIKE 'EU-%'
       AND product_name LIKE '%Wireless Mouse%' GROUP BY product_name")
    → markdown table with rows

Rules:
  - SELECT only. No INSERT/UPDATE/DELETE/DROP/ALTER.
  - Use exact table and column names from the schema.
  - If the question cannot be answered from this schema at all,
    output SELECT 1 WHERE 1=0 and stop.
```

The worked example is part of the static system prompt. It teaches
the *pattern* (inspect → ground → run), not the operator's domain.

---

## Output contract

```python
@dataclass(slots=True, frozen=True)
class ProbeRecord:
    table: str
    column: str
    op: str
    result: str              # truncated to ~500 chars for logging

@dataclass(slots=True, frozen=True)
class SqlRetrievalOutcome:
    outcome: Literal['answered', 'empty', 'unsupported']
    result_markdown: str | None
    attempted_sql: str | None
    probe_trail: list[ProbeRecord]
```

States:

- **`answered`** — `run_select` produced ≥1 row.
  `result_markdown` is non-None; `attempted_sql` is the SELECT that
  produced it; `probe_trail` may be empty (some queries don't need
  probing).
- **`empty`** — `run_select` ran cleanly and returned 0 rows on the
  last attempt. `result_markdown=None`, `attempted_sql` is the last
  SELECT, `probe_trail` has whatever the LLM inspected.
- **`unsupported`** — one of: cap exhausted; LLM emitted
  `SELECT 1 WHERE 1=0` (its "can't answer" sentinel); every
  `run_select` errored; empty `schemas` list (early return).

### Answerer integration

`AnswerAgent.answer(question, hits, *, sql_outcome: SqlRetrievalOutcome | None)`
replaces the current `sql_context: str | None` parameter. Caller-side
change in `CorpusAgent.query` is one line.

- `outcome='answered'` — existing markdown-table prompt section runs
  verbatim, using `sql_outcome.result_markdown`. Behaviour preserved.
- `outcome='empty'` — new prompt section:

  ```
  ## SQL attempt (no matching rows)
  Tried: {attempted_sql}
  Observations from inspect_table:
    {probe_trail formatted as 'table.column op → result' lines}
  ```

  Plus an additional instruction line: *"If SQL ran but matched no
  rows, do not say 'I don't have enough information.' Tell the user
  the closest available values from the probes and suggest a refined
  query."*

- `outcome='unsupported'` — no SQL section in the prompt; behaves
  like today's `sql_context=None`.

The `_NO_INFO_TEXT` short-circuit at `answerer.py:138-140` is narrowed:
it now fires only when `hits` is empty AND `sql_outcome` is `None` or
`outcome='unsupported'`. The `empty` outcome carries enough signal
that the LLM should respond informatively even without unstructured
hits.

---

## Error handling & guardrails

| Concern | Handling |
|---------|----------|
| Probe of non-existent table/column | `inspect_table` raises `ValueError`; pydantic-ai surfaces it to the LLM as a tool error so it can self-correct |
| Probe of system table (`_schemas`, `sqlite_master`, etc.) | Allow-list check rejects — these never appear in `schemas` so they're not whitelisted |
| `run_select` with non-SELECT SQL | Existing regex rejects; returns "SQL must start with SELECT" to LLM |
| `run_select` raises sqlite3.Error | Error message returned to LLM as the tool result (today this terminates the loop) |
| `run_select` returns rows but exceeds row cap | Truncate to `max_rows_in_result`, append a `(+N more rows)` footer line so the LLM knows there's more |
| Loop hits `max_steps` | Return `outcome='unsupported'` with the trail and `last_attempted_sql` if any |
| Empty schemas list | Unchanged early-return: `outcome='unsupported'`, empty trail |

The existing SQL-injection test surface stays untouched —
`run_select` keeps its current guarantees. `inspect_table` cannot
accept raw SQL by design.

---

## Testing strategy

| Layer | File | New tests |
|-------|------|-----------|
| Unit — probes | `tests/unit/corpus_search/test_sql_retriever.py` (rewrite) | One test per `op` against a tmp sqlite db; allow-list rejection (unknown table; unknown column); row cap; SQL error message returned (not raised) |
| Unit — loop | same file | Mock the agent's tool-call sequence to produce each outcome (`answered` after 0 probes; `answered` after probes; `empty` after probes; `unsupported` on cap exhaustion; `unsupported` on sentinel SELECT) |
| Unit — answerer | `tests/unit/rag/test_answer_agent.py` (new file if absent) | `outcome='answered'` → existing path; `outcome='empty'` → probe trail in prompt + no `_NO_INFO_TEXT`; `outcome='unsupported'` + empty hits → `_NO_INFO_TEXT` |
| Integration | `tests/integration/test_corpus_agent_structured.py` (extend) | End-to-end with a synthetic db whose labels don't match the question literal AND has the column-name overload (text year-tag + REAL same-prefix column). Assert non-empty outcome with the correct row. |
| Regression | new `tests/integration/test_corpus_query_grounding.py` | Synthetic-but-shaped-like-the-real-bug fixture; reproduces the failure mode in a way safe to commit (no operator labels). |

All five layers are required. The unit tests stay fast (no LLM
calls); the integration test uses a stubbed `FireflyAgent` that
deterministically replays a tool-call script.

### What about the existing 6 tests?

`tests/unit/corpus_search/test_sql_retriever.py` is rewritten. The
two tests that exercised the public surface
(`test_retrieve_returns_markdown_table`,
`test_retrieve_returns_none_for_empty_schemas`) become
`outcome='answered'` / `outcome='unsupported'` variants. The
`test_retrieve_rejects_non_select_sql` and
`test_retrieve_returns_none_on_sql_error` semantics move under
`run_select`-tool tests, since that's where SELECT validation and
error handling now live. `test_build_schema_context` is retained
with a tighter assertion (no `sample <col> values:` line, since
that heuristic is removed). `test_execute_returns_none_for_empty_result`
stays — `_execute` still exists as a helper.

---

## Rollout

- No database migrations.
- No new env vars or feature flags.
- No changes to the MCP tool surface (`corpus_query`'s JSON shape is
  unchanged; the `cited_sources` etc. fields keep their meaning).
- `AnswerAgent.answer` signature changes from
  `sql_context: str | None` to `sql_outcome: SqlRetrievalOutcome | None`;
  the only in-repo caller is `CorpusAgent.query`, so this is a
  contained refactor.

## Risks

- **Agent thrashing under Haiku.** Mitigation: hard `max_steps=8`;
  the worked example shapes the loop; on cap exhaustion the answerer
  still has unstructured hits to fall back on.
- **Probe latency tax on every query.** Acceptable until the
  follow-up probe-cache PR lands. Worst case is ~2-4× current SQL
  stage latency, in line with the user's stated budget.
- **Test-mocking brittleness.** Tool-call replay scripts can be
  fragile if pydantic-ai changes its internal call format. Mitigation:
  drive the loop via `FireflyAgent`'s public `run()` with stubbed
  tools, not via mocking the LLM client directly.
