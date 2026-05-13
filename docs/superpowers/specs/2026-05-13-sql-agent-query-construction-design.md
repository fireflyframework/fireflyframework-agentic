# SQL agent: query-construction fixes

Date: 2026-05-13
Owner: javier-alvarez
Related issues: #161 (discriminator filter), #162 (parent-level GROUP BY), #163 (sibling-column scan)
Module: `fireflyframework_agentic/rag/retrieval/sql.py`

## Background

The agentic text-to-SQL retriever in `sql.py` lets an LLM inspect a SQLite corpus, then write a final SELECT. Three failure modes are documented in the linked issues:

1. **#161** — when a fact table mixes metrics in one column (`metric_line` with values `Total Revenue`, `Active Headcount`, `Operating Expense`), the agent sometimes writes `SUM(value)` without filtering on the discriminator. Result: a semantically meaningless sum across heterogeneous rows.
2. **#162** — when a hierarchy exists (`business_unit` is parent of `team`), and the user asks for a metric "by business_unit", the agent sometimes returns per-team rows instead of one aggregated row per BU.
3. **#163** — when the obvious column for a concept is NULL for the requested row, the agent stops at the first lookup instead of scanning sibling columns whose names share semantic tokens.

All three are query-construction reasoning errors. The agent already has the right tools (`distinct_values`, `find_similar`, `numeric_summary`) and the schema. The lift is in:
- giving the agent richer signals at prompt-time (so it sees discriminators and parent-child relationships without having to probe), and
- adding explicit worked examples and rules for the three patterns.

## Goals

- Fix all three failure modes for the synthetic repros in the linked issues.
- Keep the change small and focused on `sql.py`; no schema-model field additions, no new tools.
- Preserve all existing test behaviour: every current unit test in `tests/unit/corpus_search/test_sql_retriever*.py` and `tests/examples/corpus_search/test_*.py` continues to pass.

## Non-goals

- Adding an opt-in `discriminator: bool` field on `ColumnSpec`. Static annotations require user maintenance and don't help existing schemas; live cardinality is more reliable.
- Adding new inspect ops (e.g. `child_count_per_parent`, `aggregate_columns`). The existing `distinct_values` + `count` + the new cardinality annotation cover the signal we need; new ops widen the tool surface for unclear gain.
- Computing cardinality at ingest time. Schemas can outlive data shape; per-retrieve cost is one `COUNT(DISTINCT col)` per string column, which is negligible against an LLM call.
- Fixing every conceivable SQL-agent reasoning bug — only the three failure modes listed above.

## Design

### Component 1: schema-context cardinality annotation

**Location:** `_build_schema_context()` in `sql.py`.

**Change:** widen the signature from `(schemas)` to `(schemas, db_path)`. For each string-typed column, run `SELECT COUNT(DISTINCT col) FROM table` against `db_path` and annotate the column descriptor in the prompt with the result:

```
Before:
- finance_fact: year (string), market (string), metric_line (string), value (float)

After:
- finance_fact: year (string, 5 distinct), market (string, 12 distinct), metric_line (string, 3 distinct), value (float)
```

Rules:

- Only string-typed columns get the annotation. Numeric/date columns are not annotated (their cardinality is rarely informative for the failure modes we target, and the column type already signals "this is the measure axis").
- If the cardinality query fails (e.g. table empty, column does not yet exist in the DB despite being in the schema), fall back to the un-annotated descriptor and log a warning. Do not raise — the retriever must remain robust to schema/DB drift.
- One `COUNT(DISTINCT)` per string column, executed via the existing `_connect(db_path)` helper. Aggregated into a single connection lifecycle per `_build_schema_context` call.

**Why this addresses #161 and #162:**

- `metric_line (string, 3 distinct)` reads to the LLM as "this is a small categorical axis." Combined with the worked example, the agent learns to call `distinct_values` and add the WHERE filter.
- `business_unit (string, 2 distinct), team_name (string, 4 distinct)` makes the parent/child cardinality difference visible at a glance, supporting the "by business_unit → GROUP BY business_unit" inference.

### Component 2: `_SYSTEM` prompt updates

**Location:** the `_SYSTEM` string in `sql.py`.

**Changes:**

1. Add a paragraph to the tool-description preamble explaining the cardinality annotation:

   > Each string column in the schema below is annotated with its distinct-value count (e.g. `metric_line (string, 3 distinct)`). A low count (typically <50) signals a categorical / discriminator axis: a column you may need to filter on with WHERE before aggregating other columns in the same table. A count near the row count signals a unique identifier.

2. Add three numbered rules to the Process section:

   - **Discriminator-before-aggregate rule (#161):**
     > Before SUM/AVG/COUNT over a numeric column, scan the table's string columns annotated with low distinct counts. If any look like categorical axes (3–50 distinct values, names like `*_line`, `*_type`, `*_category`, `kpi`, `metric`), call `distinct_values` on them and decide whether your aggregate needs a WHERE filter. Failing to filter when the column mixes metric categories produces a meaningless sum.

   - **Group-by phrasing rule (#162):**
     > If the question says "by X", "for each X", "per X", or "across X", you almost certainly want `GROUP BY X` with an aggregate over the metric column — not a flat `SELECT *`. Use the parent column's distinct count from the schema annotation to confirm you are grouping at the level the user asked for.

   - **Sibling-column scan rule (#163):**
     > If `run_select` returns 0 rows on a single-column lookup, or returns NULL for the column you queried, do NOT immediately conclude "no record." Look at the table's other columns. If any column name shares semantic tokens with the question (e.g. the question asks about "change" and the table has `role_change`, `recorded_movement`, `effective_date_of_route_change`), inspect those columns before answering. Only conclude "no record" after every semantically-relevant column has been probed.

3. Add three worked examples to `_SYSTEM`:

   - **Worked example 3 — discriminator filter (synthetic, mirrors #161):**
     ```
     Question: "What is 2024 revenue for market EU?"
     Schema: finance_fact (year string 5 distinct, market string 12 distinct,
                           metric_line string 3 distinct, value float)
     Reasoning: metric_line is 3-distinct — almost certainly a categorical
                discriminator. SUM(value) without filtering it mixes
                revenue, headcount, and expense.
     inspect_table(finance_fact, metric_line, 'distinct_values')
       -> ['Total Revenue', 'Active Headcount', 'Operating Expense']
     run_select("SELECT SUM(value) FROM finance_fact
                 WHERE year='2024' AND market='EU'
                 AND metric_line='Total Revenue'")
     ```

   - **Worked example 4 — GROUP BY at parent level (synthetic, mirrors #162):**
     ```
     Question: "What is the average achievement by business_unit?"
     Schema: performance (team_id int, team_name string 4 distinct,
                          business_unit string 2 distinct, achievement_pct float)
     Reasoning: "by business_unit" → GROUP BY business_unit. The schema
                shows 2 BUs and 4 teams — that 2:4 ratio confirms the
                parent/child hierarchy.
     run_select("SELECT business_unit, AVG(achievement_pct)
                 FROM performance GROUP BY business_unit")
     ```

   - **Worked example 5 — sibling-column scan (synthetic, mirrors #163):**
     ```
     Question: "Has there been any structural change for employee 42?"
     Schema: employee_changes (employee_id int, name string ~unique,
                               recorded_movement string 8 distinct,
                               effective_date_of_route_change string 12 distinct,
                               role_change string 6 distinct)
     Reasoning: 'recorded_movement' is the obvious column. But three
                columns share semantic tokens with "structural change"
                — check all of them before concluding "no record."
     run_select("SELECT recorded_movement
                 FROM employee_changes WHERE employee_id=42")
       -> recorded_movement = NULL
     run_select("SELECT recorded_movement, effective_date_of_route_change, role_change
                 FROM employee_changes WHERE employee_id=42")
       -> effective_date_of_route_change='2024-07-01', role_change='New region'
     ```

### Component 3: tests

- **Unit (`test_sql_retriever.py` extensions):**
  - `_build_schema_context` annotates string columns with their `COUNT(DISTINCT)` from the DB.
  - `_build_schema_context` falls back gracefully (no annotation, warning logged) when the cardinality query fails (e.g. the table does not exist yet in the DB).
  - Numeric/date columns are NOT annotated.
- **Replay-style tests (`test_sql_retriever_query_construction.py`, new):**
  - For each of the three failure modes, build a synthetic DB and schema matching the issue's repro, fake `_sql_agent.run` to invoke the tools in the "expected" sequence (i.e. the sequence the new prompt should drive), and assert the resulting outcome contains the correct SQL.
  - These are not LLM-driven — they pin the expected tool-call sequence so we have regression coverage against future prompt edits.
- **No changes to E2E tests** in `tests/examples/corpus_search/` — those exercise live models and are best updated manually if the LLM behaviour changes.

### Component 4: manual verification

Before commit, run a manual repro for each issue against a small fixture DB:

- #161: build `finance_fact` with the issue's sample rows. Ask "What is the 2024 revenue for market EU?" and confirm the agent's final SQL includes `AND metric_line='Total Revenue'` and the result is 1200.
- #162: build `performance` with the issue's sample rows. Ask "What is the average achievement by business_unit?" and confirm the result has 2 rows.
- #163: build `employee_changes` with the issue's sample rows. Ask "Has there been any structural change for employee 42?" and confirm the agent inspects all three semantically-relevant columns and reports the route change + role change.

Manual steps live in the PR body.

## File-by-file change list

- `fireflyframework_agentic/rag/retrieval/sql.py`:
  - `_build_schema_context(schemas)` → `_build_schema_context(schemas, db_path)`. Annotates string columns with distinct count.
  - `retrieve()` passes `self._db_path` to `_build_schema_context`.
  - `_SYSTEM` gets the cardinality-annotation paragraph, three new rules, and three new worked examples.
- `tests/unit/corpus_search/test_sql_retriever.py`: extend `_build_schema_context` tests for the cardinality annotation.
- `tests/unit/corpus_search/test_sql_retriever_query_construction.py` (new): three replay-style regression tests.
- `CHANGELOG.md`: one line under "Fixed" linking the three issue numbers.

## Risks

- **LLM may ignore the new rules.** Prompt edits are best-effort. The cardinality annotation in the schema context is the structural signal that does most of the work; the rules and examples reinforce it.
- **Cardinality query cost.** One `COUNT(DISTINCT col)` per string column per `retrieve()` call. For corpora with hundreds of string columns this could add a few hundred ms. Mitigation: if this becomes a real cost, cache the per-table annotations on the retriever instance keyed by DB mtime. Not implementing the cache now — premature optimisation.
- **Heuristic vs literal in the discriminator rule.** The rule mentions "names like `*_line`, `*_type`, `*_category`, `kpi`, `metric`" — these are guidance, not enforcement. Real-world column names won't always match. The cardinality annotation is the actual structural signal; the names are a hint.

## Rollout

Single PR off `main` referencing #161, #162, #163. No feature flag — the cardinality annotation is small, additive, and degrades to the current behaviour if the cardinality query fails. After merge, the next E2E run will exercise the new prompt.
