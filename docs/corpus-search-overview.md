# Corpus Search — how it answers questions

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

This document explains, in plain language, what happens when you drop
documents into a folder, point the framework at them, and ask a
question. It covers both pillars of the system — **unstructured search**
(documents written for humans) and **structured search** (tables and
spreadsheets) — and where the design wins or loses against alternatives
that extract data every time you query.

It is intentionally not a code walk-through. If you want the source,
start at `fireflyframework_agentic/rag/agent.py::CorpusAgent.query`.

---

## TL;DR

1. **Ingest is a one-time cost.** You give the system a folder. It
   converts each document to Markdown, splits it at heading boundaries,
   embeds each chunk, and indexes everything inside a single SQLite
   file. Tables (CSV / Excel) get a separate, typed treatment: an LLM
   reads a few rows, proposes a relational schema, and the system loads
   the rows into typed tables you can later query with SQL.
2. **A question fans out into two parallel paths.** The unstructured
   path does hybrid lexical + semantic search and asks an LLM to write
   a cited answer. The structured path lets a smaller LLM inspect the
   real data in your tables and write a SELECT against them.
3. **One answerer combines both signals.** A single LLM sees both the
   document chunks and the SQL result (or the closest probes if the
   SQL came back empty) and produces one grounded answer with
   `[chunk_id]` citations.

That separation matters: questions like *"how much revenue did Europe
do last quarter, and what did the press release say about it?"* only
work because the same answer pass sees both kinds of evidence.

---

## How ingest works

### Unstructured (PDFs, Word, slides, Markdown, plain text)

```
folder/  ──►  Markitdown converter  ──►  Markdown  ──►  Markdown chunker
                                                              │
                                                              ▼
                                               sqlite (chunks + FTS5)
                                                              │
                                                              ▼
                                                  sqlite-vec (embeddings)
```

- **Converter.** Every file goes through Markitdown so that PDFs,
  DOCX, PPTX, XLSX, HTML, and plain text all become Markdown before
  anything else looks at them. The downstream code only knows one
  format.
- **Chunker.** The chunker walks the Markdown structure: each section
  becomes a chunk, prefixed with the heading path
  (`{H1} > {H2} > {H3}`). Long sections fall back to fixed-size
  splitting; short ones are skipped. The heading path is also stored in
  metadata so the system can show users where an answer came from.
- **Indexes.** Two indexes live in the same SQLite file:
  - **FTS5** (Full-Text Search 5, SQLite's built-in inverted index)
    with Porter stemming and diacritic stripping. This is the
    "keyword" side: it finds chunks that contain words the user
    actually typed.
  - **sqlite-vec** holds embeddings (1536-d by default, OpenAI's
    `text-embedding-3-small`). This is the "semantic" side: it finds
    chunks that mean roughly the same thing as the question even when
    they share no keywords.
- **Idempotence.** A small ledger table records the content hash of
  every ingested file. Re-running ingest skips files whose hash has not
  changed — you can point the system at the same folder every day and
  pay only for the deltas.

### Structured (CSV, Excel)

Tabular files take a separate path because keyword/embedding search is
not the right primitive for them — you don't want to "retrieve a
similar row to corporate sales 2024-Q4", you want to *aggregate* it.

```
folder/foo.xlsx  ──►  schema discovery (LLM reads a sample)
                              │
                              ▼
                  TargetSchema (proposed types + foreign keys)
                              │   (the human can review/edit)
                              ▼
                  Structured pipeline: typed INSERTs into SQLite
                              │
                              ▼
                  _schemas table (so the query side knows the shape)
```

- **Discovery.** An LLM is given the first ~50 rows and infers column
  types, picks a primary key, proposes foreign keys across files. The
  output is a `TargetSchema` JSON document. You can review it, fix
  obvious mistakes, and feed it back to refine.
- **Load.** Once the schema is accepted, the pipeline streams the
  rows into real SQLite tables (one per file or per sheet). Those
  tables live in the same `corpus.sqlite` as the chunks — so a single
  query can hit both.
- **No extraction pass.** Crucially, the LLM only sees a sample at
  ingest time; the actual rows never go through an LLM. This is the
  opposite of systems that re-extract structure on every question.

---

## How a query works

The entry point is `CorpusAgent.query(question)`. Two independent
retrieval paths run in parallel; their outputs converge in a single
answer pass.

```
            question
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
 unstructured       structured
   pipeline          pipeline
       │                 │
       ▼                 ▼
   top-k chunks      SQL result
   (with citations)  or probe trail
       │                 │
       └────────┬────────┘
                ▼
          AnswerAgent (Sonnet)
                │
                ▼
     Answer(text, citations, cited_sources)
```

### The unstructured path

1. **Query expansion.** A small LLM (Haiku) rewrites the question
   into 3–5 variants — different phrasings, expansions of acronyms,
   alternative angles. This boosts recall on questions where the
   user's wording doesn't match the document's wording.
2. **Hybrid retrieval.** For each variant the system runs two
   searches in parallel:
   - FTS5 keyword search ranks chunks by lexical overlap.
   - sqlite-vec vector search ranks chunks by embedding similarity.
   The two ranked lists are fused with Reciprocal Rank Fusion (a
   standard, parameter-free recipe that rewards chunks that show up
   high in either list). Up to 30 candidates per variant, fused into
   one pool of ~20.
3. **Reranking.** A second Haiku pass reads the question and the top
   ~20 candidates and picks/reorders the best `top_k`. Where the
   first pass is fast and lexical, this pass is "does this chunk
   actually answer the question?". On failure (LLM error, timeout) we
   fall back to the original retrieval order — never worse than no
   reranker.

### The structured path (the inspect loop)

If there are no registered schemas, this path is skipped and the
unstructured path carries the query. When there *are* schemas, an
agentic loop runs:

1. The LLM sees the schema (table + column names + types) and the
   question.
2. It can call `inspect_table(table, column, op, value?)` to peek at
   the data — distinct values, counts, sample rows, value ranges, and
   most importantly **`find_similar(value=…)`** which finds rows
   whose value contains the user's literal string, case-insensitively
   and accent-folded. Crucially, `find_similar` tokenises the value:
   *"Sam Lee"* matches *"Patrick Ulric Bréwster Fernández"*
   even though no single SQL `=` or naive `LIKE` would.
3. Once the LLM is confident, it calls `run_select(sql)` with the
   final SELECT. The query is sandboxed (SELECT-only, errors are
   surfaced back to the loop so the LLM can self-correct).
4. The loop stops on the first successful query, or after a small
   budget if the question can't be answered from the schema.

The result is one of three things:
- **answered** — a markdown table of rows, plus the SQL the LLM
  ran (so a reviewer can sanity-check it).
- **empty** — the SELECT was syntactically fine but matched nothing.
  The "probe trail" — every `inspect_table` call the LLM made — is
  preserved and forwarded to the answerer, so the user can be told
  *"no exact match for 'Sam Lee', but the closest names I
  found are: …"*. This is exactly the "did you mean" experience.
- **unsupported** — the LLM decided the question is out of scope of
  the available schemas (no relevant table) or every attempt errored
  out.

### The answer pass

A single Sonnet call gets:
- The question.
- The top-k unstructured chunks (each prefixed with a stable
  `[chunk_id]`).
- If the structured path produced a table, the markdown table.
- If it produced an empty result, the attempted SQL and the probe
  trail.

Sonnet is instructed to:
- Answer **strictly** from the evidence in the prompt; if nothing
  supports an answer it must say *"I don't have enough information."*
- Cite chunks inline as `[chunk_id]` after each claim that came from
  one.
- When the SQL came back empty, **not** fall back to the "no
  information" reply — instead, surface the closest values from the
  probe trail and suggest a refined query.

The output is a structured `Answer` with the text, the list of cited
chunk IDs, and a mapping back to source paths (so the UI can show
*"this came from finance-2025.pdf"*, not just an opaque ID).

---

## Why this is better than "extract everything on every query"

Some systems (Cowork is the canonical example in our space) don't
maintain an index. Each question triggers a fresh extraction pass over
the documents: the LLM reads them, pulls out facts, reasons over them,
and answers. That's elegant in its simplicity but it has hard
problems:

| Concern | Cowork-style (extract every time) | Firefly corpus search |
|---|---|---|
| **Cost per question** | O(corpus size) — you pay to re-read every relevant document each time. | O(top-k chunks + one SQL). The corpus is read once at ingest; queries fetch a handful of chunks. |
| **Latency** | Grows with the corpus. A 5,000-document drop is unusable for interactive use. | Roughly constant: ~1–3 s on small corpora dominated by the LLM, not retrieval. |
| **Consistency** | A second question may pull different facts than the first because the extraction is non-deterministic. | The index is the source of truth. Two identical questions get the same retrieved evidence. |
| **Auditability** | "The model said X" — you cannot show *where* X came from unless you re-extract and pray it matches. | Every claim cites a `[chunk_id]` that resolves to a specific document and section. Reviewers can click through. |
| **Structured + unstructured together** | Either you have one or you ingest the spreadsheet as text (losing the ability to aggregate) — both are bad. | The structured path can do `SUM(revenue) GROUP BY region` *and* the unstructured path can pull the matching press release in the same question. |
| **Incremental updates** | Re-extract everything on every change. | Content-hash dedupe; only the changed file gets re-embedded. |
| **Cost cap** | Hard to predict. Each question can cost a lot if it has wide scope. | Predictable: ~3–5 LLM calls per question (expander + reranker + answerer + optional SQL loop), independent of corpus size. |

The trade-off we accepted: **we pay an upfront ingest cost** (embedding
each chunk once, ~$0.02 per 1,000 chunks at current OpenAI pricing).
That cost is sunk; everything afterwards is cheap.

---

## Where it shines today

- **Mixed corpora.** Folders that contain PDFs *and* CSVs and questions
  that span both. Cowork would have to extract twice; we just run two
  retrievers and one answer pass.
- **Recurrent-question workloads.** Customer-facing assistants,
  internal Q&A bots, anything where the same documents are queried
  thousands of times.
- **Fuzzy entity matching on tables.** `find_similar` with
  accent-folding + token-AND/OR catches the kinds of human-typed
  variations that crash a literal SQL `=`: *"Sam Lee"* →
  *"Patrick Ulric Bréwster Häthaway Önken"*. The answerer can
  prepend *"no exact match, but here are the closest names"* and
  still return the row.
- **Citations.** Every claim in the final answer is anchored to a
  chunk, which is anchored to a document and a section heading. This
  is what makes the system enterprise-deployable: it survives a "where
  did you get that" audit.

---

## Where it can fail today (and where to improve)

Each of these is a known gap. The headline is: **the system is great
when the question is narrowly answerable from a few chunks plus,
optionally, a small SQL query**. It struggles in roughly four shapes.

### 1. Multi-hop reasoning across documents

*"Who did the manager of Sam Lee sign the 2024 services deal
with?"* — this needs (a) find Javier, (b) find his manager, (c) find
the manager's signed deals, (d) extract the counterparty. The
structured path can handle (a)–(c) only if all three relationships
live in tables; otherwise we fall back to hoping the answer is in one
chunk. **Improvement path:** an iterative orchestrator that turns
multi-hop questions into a sequence of retrieval-then-narrow steps,
not the single retrieval pass we do today.

### 2. Entity resolution across documents

*"Has Acme ever been mentioned as a customer?"* — answer hinges on
whether the embedding or BM25 ranking surfaces every mention. There is
no entity index, so if Acme is referred to as *"Acme Corp"* in one
file and *"ACME, Inc."* in another, recall depends on the embedding
model. **Improvement path:** a lightweight entity column built during
ingest (`mentions` table with normalised name + chunk_id) that the
query path can JOIN against.

### 3. Tables embedded in PDFs

The structured pipeline only ingests CSV/Excel. PDFs with tables go
through the unstructured pipeline, which means the table becomes text
in a chunk — fine for narrative answers, useless for
`SUM(...) GROUP BY ...`. **Improvement path:** extract tables from
PDFs at ingest, materialise them as if they were CSVs, and register
the schema like any other tabular source.

### 4. Cross-corpus federation

Each `corpus_id` is isolated by design (see the per-corpus auth
work). A question that spans two corpora needs the caller to fan it
out and merge — we don't do that today. **Improvement path:** a
federation layer that runs the same question against multiple corpora
and merges citations, with a token model that grants access to a
named set rather than a single corpus.

### 5. Reliability of the SQL loop on hostile schemas

The inspect loop is robust for clean schemas (~5–20 columns). On
schemas with hundreds of columns or obscure naming, the LLM can get
stuck inspecting the wrong column or compose nonsensical SQL. We cap
the loop at 8 tool calls so it doesn't run away, but the failure
mode is "unsupported" rather than "graceful degradation". **Improvement
path:** schema summarisation hints stored at ingest time, plus a
fallback that runs the unstructured retriever on the schema docs and
seeds the loop with the relevant column hints.

### 6. No diversity in the chunk pool

The reranker picks the best chunks but does not enforce diversity. On
questions with multiple aspects (*"compare 2023 and 2024 revenue, and
what changed in the strategy"*), the top-k can all be about the same
aspect because they all score highly on embedding similarity.
**Improvement path:** Maximal Marginal Relevance (MMR) on the
reranked pool, or letting the reranker explicitly score "covers a
different angle".

---

## How to push it further than Cowork

Three concrete bets where the indexed model can outperform the
extract-every-time model:

1. **Sub-second answers on the long tail.** Pre-compute and cache the
   reranker output for the top N most-frequent question patterns
   (FAQ-style). The same pattern with different parameters
   ("revenue for Q4 2023" vs "revenue for Q4 2024") can share the
   retrieval cache and pay only the answer-LLM cost.
2. **Continuous reflection.** Because the corpus is durable, we can
   run a background job that produces a daily "deltas" digest of new
   documents and pushes it into the system prompt of the answerer.
   Cowork cannot do this — it has no persistent state between
   queries.
3. **Pre-computed structured views.** When the ingest LLM proposes a
   schema, it can also propose useful aggregations
   (`monthly_revenue_by_region`) and materialise them at ingest. The
   query LLM then writes SELECTs against the views — fewer joins,
   smaller search space, much higher success rate on multi-table
   questions.

Each of those compounds: the more often we query the same corpus,
the more pre-computation we can amortise.

---

## A note on safety and access

The per-corpus auth (`firefly-mcp-http` HTTP transport) ensures a
token only grants access to one corpus. Combined with the answerer's
"answer strictly from evidence" instruction, this gives us two
properties Cowork cannot match cheaply:

- **A leak of one corpus's token cannot exfiltrate any other.**
- **The answer can never claim something that wasn't in the
  retrieved evidence** (the LLM is told to reply *"I don't have
  enough information"* if it can't cite, and the deployment can
  enforce that callers never see uncited claims).

See `docs/deploy/mcp-corpus-auth.md` for the wire-level details and
`docs/security.md` for the prompt-guard / output-guard layers that
catch injection attempts on the way in and PII / secret leaks on the
way out.

---

## Where to read the code

- `fireflyframework_agentic/rag/agent.py` — `CorpusAgent.query` is the
  entry point that orchestrates everything.
- `fireflyframework_agentic/rag/retrieval/hybrid.py` — FTS5 + vector
  fusion (RRF).
- `fireflyframework_agentic/rag/retrieval/expander.py` — Haiku query
  expansion.
- `fireflyframework_agentic/rag/retrieval/reranker.py` — Haiku
  listwise reranker.
- `fireflyframework_agentic/rag/retrieval/sql.py` — the inspect loop,
  `find_similar`, the `_SYSTEM` prompt that drives the LLM.
- `fireflyframework_agentic/rag/retrieval/answerer.py` — Sonnet
  answer synthesis with citations.
- `fireflyframework_agentic/rag/ingest/` — both ingest pipelines and
  the schema-discovery LLM.
- `fireflyframework_agentic/content/markdown_chunker.py` — the
  structure-aware chunker.
