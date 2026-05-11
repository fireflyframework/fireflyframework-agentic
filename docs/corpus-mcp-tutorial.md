# Firefly Corpus MCP — End-to-End Tutorial

A step-by-step guide for running the corpus search workflow against your
own data, using Claude Desktop as the user interface. End-to-end, on
your own laptop — no Firefly backend, no shared infrastructure.

This guide covers:

1. Getting the code (clone, branch, install).
2. One-time configuration (env, embedding + LLM credentials).
3. Wiring the `firefly-corpus` MCP server into Claude Desktop.
4. Running the full ingest → query workflow inside a Claude Desktop
   conversation, against your own folder of documents.
5. Exporting answers to an output document (Markdown, Word, HTML).
6. Handling the transient errors you will see in real use.
7. (Optional) Opening a pull request if you improve anything.

> **Why this exists.** You point Claude Desktop at a folder of your own
> documents — PDFs, Word docs, spreadsheets, CSVs — and it builds a
> searchable SQLite + vector corpus locally. From then on you can ask
> natural-language questions and get answers grounded in those
> documents, with citations. Nothing leaves your laptop except LLM and
> embedding API calls.

---

## 0. Prerequisites

| Requirement | Notes |
|---|---|
| macOS or Windows | The MCP server is pure Python; Claude Desktop is officially supported on both. Linux works if you run the server manually. |
| Git | To clone the repository. |
| Python 3.11+ | The repo's `pyproject.toml` pins the minimum. |
| `uv` | Used to run the server in an isolated environment. Install via `curl -LsSf https://astral.sh/uv/install.sh \| sh` on macOS/Linux or `pip install uv` on Windows. |
| Anthropic API key | For query expansion, reranking, and answer synthesis. |
| Azure OpenAI embedding deployment | A `text-embedding-3-small` (or compatible) deployment, plus the host URL and key. |
| Claude Desktop | Latest version from `https://claude.ai/download`. |

If your use case does not allow Azure OpenAI, replace the embedding
binding with another provider before starting — the MCP server reads
the binding from environment variables at startup, so any swap happens
in `.env` rather than in code.

---

## 1. Get the code

### 1.1 Clone the repository

```bash
git clone git@github.com:fireflyframework/fireflyframework-agentic.git
cd fireflyframework-agentic
```

(Use the HTTPS URL —
`https://github.com/fireflyframework/fireflyframework-agentic.git` — if
you do not have SSH keys configured.)

### 1.2 Create a working branch (recommended)

Even if you do not plan to push changes back, working on a branch keeps
`main` clean and avoids accidental edits to tracked files:

```bash
git checkout -b try/<your-initials>-corpus-demo
```

The repo convention is **always branch from `main`; never push directly
to `main`**.

### 1.3 Install dependencies

```bash
uv sync
```

`uv sync` resolves the lockfile and creates a `.venv/` in the repo. You
do not need to activate it manually — `uv run` handles that.

---

## 2. Configure secrets and storage

### 2.1 Create your `.env`

Copy the template and fill in real values:

```bash
cp .env.template .env
```

The MCP server reads `.env` from the repo root at startup, so this is
also where you point at your corpus storage:

```dotenv
# LLM provider
ANTHROPIC_API_KEY=sk-ant-...

# Azure OpenAI embedder
EMBEDDING_BINDING_HOST=https://<your-resource>.openai.azure.com
EMBEDDING_BINDING_API_KEY=...

# Corpus storage — override the /tmp default for any real use.
CORPUS_ROOT=/Users/<you>/firefly-corpora
```

Create the corpus storage folder once:

```bash
mkdir -p "$CORPUS_ROOT"
```

> **Privacy.** `.env` is gitignored. Keep your `CORPUS_ROOT` outside the
> repo's tracked tree — the repo gitignores `/drop/`, `/kg/`, and
> `/runs/`, so if you do stage data inside the repo, stage it under one
> of those paths and never under `examples/` or `docs/`.

### 2.2 Smoke-test the server

Before wiring it into Claude Desktop, confirm it boots:

```bash
uv run python examples/corpus_search/mcp_server.py
```

It will block, waiting for JSON-RPC over stdin. You should see a single
log line on stderr similar to:

```
[mcp_server] ... INFO firefly.mcp_server: starting firefly corpus_rag MCP server (CORPUS_ROOT=/Users/<you>/firefly-corpora)
```

Press `Ctrl-D` (or `Ctrl-C`) to exit. If you see `missing required
env`, re-check `.env`.

---

## 3. Wire `firefly-corpus` into Claude Desktop

Claude Desktop launches MCP servers as subprocesses based on a JSON
config file.

| OS | Config path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Open the file (Claude Desktop → Settings → Developer → "Edit Config"
opens it for you) and add a `firefly-corpus` entry under `mcpServers`.
Replace `<absolute path to repo>` with the absolute path on your
machine — relative paths and `~` do **not** work here.

```json
{
  "mcpServers": {
    "firefly-corpus": {
      "command": "uv",
      "args": [
        "--directory",
        "<absolute path to repo>",
        "run",
        "python",
        "examples/corpus_search/mcp_server.py"
      ]
    }
  }
}
```

If `uv` is not on Claude Desktop's `PATH` (this happens often on
macOS, because GUI apps inherit a minimal PATH), use the absolute path
instead:

```json
"command": "/Users/<you>/.local/bin/uv"
```

Save the file, then fully **quit and relaunch** Claude Desktop (not
just close the window — `Cmd-Q` on macOS).

### Verify the connection

Open a new chat in Claude Desktop and look at the tool icon under the
input box. You should see six `firefly-corpus` tools listed:

- `list_corpora`
- `ingest_corpus_filesystem`
- `discover_corpus_schema`
- `ingest_corpus_structured`
- `corpus_retrieve`
- `corpus_query`

If they do not appear, check Claude Desktop's MCP log:

| OS | Log path |
|---|---|
| macOS | `~/Library/Logs/Claude/mcp-server-firefly-corpus.log` |
| Windows | `%APPDATA%\Claude\logs\mcp-server-firefly-corpus.log` |

Common failure modes:

- `missing required env` — `.env` not loaded; double-check `CORPUS_ROOT`
  is set and the `--directory` argument in the config points at the
  repo root that contains `.env`.
- `command not found: uv` — Claude Desktop's PATH doesn't see `uv`.
  Use the absolute path as shown above.
- The server starts and immediately exits — usually a Python import
  error. Run the smoke test from §2.2 in a terminal to see the
  traceback.

---

## 4. Prepare your data

Stage all the documents you want to query under a single folder on
your laptop, e.g.:

```
~/firefly-data/my-project/
├── policies/                # PDFs, Word docs
├── procedures/              # Markdown, HTML
├── reference-data.xlsx      # Tabular — multiple sheets
└── budget-2024.csv          # Tabular
```

Use a neutral codename in folder names — the path shows up in citation
chunk_ids and in any output document you export, so avoid putting
anything sensitive in directory or file names.

> **Two kinds of files, two ingest passes.** The corpus engine handles
> unstructured documents (PDF, DOCX, MD, HTML, …) and tabular files
> (CSV, XLSX) through different tools. You will run both passes against
> the same folder; the engine routes each file appropriately and
> deduplicates by content hash, so re-runs are cheap.

---

## 5. Run the workflow in Claude Desktop

The rest of this guide shows the exact prompts to use. Claude Desktop's
model will choose the right MCP tool from each prompt; you do not need
to invoke tools by name, but doing so removes ambiguity when the model
is hesitating.

Throughout the examples below, replace:

- `<corpus-id>` with a short, filename-safe identifier
  (e.g. `my-project`). This becomes a subdirectory name under
  `CORPUS_ROOT`.
- `<absolute path to your data folder>` with the folder from §4.

### 5.1 Check what corpora already exist

> "Use `list_corpora` to show me which corpora are currently on disk."

If the corpus_id you plan to use is already listed, either pick a new
one or be aware that subsequent ingests will append to the existing
corpus (and skip already-hashed files).

### 5.2 Discover the schema of tabular files

> "Call `discover_corpus_schema` with `corpus_id="<corpus-id>"` and
> `path="<absolute path to your data folder>"`. Review the returned
> schema and summarise the tables, their columns, and any
> data-quality flags you spot before we ingest."

The discovery agent reads every CSV / XLSX file under `path` in a
single LLM call and proposes a relational schema (tables, column types,
nullability, candidate foreign keys). **Nothing is written to the
corpus yet.**

#### Review the proposed schema

Have Claude Desktop summarise the schema in plain English. Look for:

- Numeric columns that came back as `string` — usually means the
  source spreadsheet has mixed content or stray text in the column
  header rows.
- Tables that obviously represent metadata / legend sheets (often a
  single column called `notes` or similar) and could be excluded.
- Cross-table identifiers (e.g. `employee_id`, `route_id`) that
  *should* be foreign keys but the agent did not link.

#### Apply corrections without re-uploading

If the schema needs fixes, do **not** re-run discovery from scratch.
Instead, ask Claude Desktop to call `discover_corpus_schema` again
with two extra arguments:

> "Call `discover_corpus_schema` again with the same `corpus_id` and
> `path`, but pass the previous result as `previous_schema` and add
> `corrections=\"mark employee_id in payroll as a foreign key to
> employees.id; the amount column in invoices should be numeric not
> string; rename the table sheet1 to notes_legend.\"`"

The agent will edit the prior schema in place rather than re-inferring
it from scratch. You can iterate as many times as you need.

### 5.3 Ingest the structured tables

Once the schema looks right:

> "The schema is good. Call `ingest_corpus_structured` with
> `corpus_id="<corpus-id>"`,
> `path="<absolute path to your data folder>"`, and the schema we just
> agreed on."

This writes real SQLite tables under
`$CORPUS_ROOT/<corpus-id>/corpus.sqlite`. Subsequent `corpus_query`
calls will run text-to-SQL against those tables.

> **Cost note.** `ingest_corpus_structured` is significantly more
> expensive than `ingest_corpus_filesystem` because the discovery agent
> runs an LLM pass per table batch. Get the schema right *before*
> ingesting — re-runs are idempotent, but each re-run pays the same
> cost.

### 5.4 Ingest the unstructured documents

Same folder, second pass — this time picking up the non-tabular files:

> "Call `ingest_corpus_filesystem` with `corpus_id="<corpus-id>"` and
> `root_path="<absolute path to your data folder>"`. Report the
> ingested / skipped / failed counts."

`ingest_corpus_filesystem` is idempotent (skip-by-content-hash), so it
is safe to re-run if you drop in additional documents later. Tabular
files are excluded from this pass by the engine — they are already in
the structured tables.

### 5.5 Sanity-check what was ingested

> "Use `corpus_query` against `<corpus-id>` to list the user tables in
> the structured database. Filter out internal system tables (those
> starting with `chunks`, `chunks_fts`, `ingestions`, or `_schemas`)."

You should see exactly the tables you signed off on in §5.2. If
anything is missing, the file likely failed schema validation — check
the MCP log.

### 5.6 Ask the questions

Now run the actual output. Two patterns work well:

**Pattern A — paste the question bank inline.**

> "Here are the questions I want answered. Use `corpus_query` against
> `<corpus-id>` to answer each one. Quote the figures verbatim,
> include the cited chunk_id or table name, and flag any question the
> corpus does not contain the answer to."
>
> 1. What is the total revenue for product X in FY24?
> 2. Which territories had a year-over-year decline of more than 10%?
> 3. …

**Pattern B — drop in a question document.**

Attach a document containing your questions (DOCX, PDF, MD) directly
to the Claude Desktop conversation and ask:

> "Read the attached questionnaire and use `corpus_query` against
> `<corpus-id>` to answer each numbered question in order. Do not
> open or reference any file path on disk — only use the corpus
> tools."

The "do not open files on disk" guard matters if your laptop has the
source documents in a location the model could otherwise read
directly — you want answers grounded in the **ingested corpus**, not
in a side-channel filesystem read.

---

## 6. Export answers to an output document

Claude Desktop renders Markdown, tables, and code blocks natively, and
can produce downloadable artefacts. After you have the answers:

**Markdown.** Easiest, always works:

> "Compile all the answers above into a single Markdown document with
> one section per question. Give me a download link."

**Word.** Ask for `.docx` directly — Claude Desktop generates it as an
artefact:

> "Produce the same content as a Word document with headings for each
> section."

**HTML for print-to-PDF.** Claude Desktop does not produce PDF
directly. The lowest-friction PDF path is:

> "Render the answers as a self-contained HTML document with proper
> page-break styling. I will print it to PDF myself."

Then open the HTML, `Cmd-P` / `Ctrl-P`, and "Save as PDF". Avoid asking
for an interactive HTML with a "Print" button — it adds clutter
without changing the outcome.

---

## 7. Handling transient errors

You **will** see these in any real use. They are part of normal
operation, not configuration bugs.

| Error | What it means | What to do |
|---|---|---|
| `overloaded_error` / HTTP 529 from Anthropic | The Anthropic API is at capacity. | Retry the same prompt. Almost always clears within seconds. |
| `Exceeded maximum retries (3) for output validation` | The schema-discovery agent produced output that failed the server's validator three times in a row. | Retry once or twice. If it persists, simplify the folder: ensure the path contains only CSV / XLSX files, no empty files, no broken workbooks. Check the MCP log for the exact validation failure. |
| Timeouts on large folders | Schema discovery batches files but very large folders can still exceed the request budget. | Split the folder into subfolders and discover each separately, then ingest. |
| `missing required env` at MCP startup | `.env` not loaded. | Confirm `--directory` in the Claude Desktop config points at the repo root that contains `.env`. |
| Citations resolve but answers feel stale | You re-ingested but the agent still sees old content. | The conversation may have cached results. Start a new Claude Desktop chat — agents are per-process and cached, but each new conversation re-binds. |

> **Never silently retry past a third failure of the same call.** If
> the same tool fails three times with the same error, stop and
> investigate. Persistent failure almost always points at a corrupt
> source file, a misconfigured env var, or a malformed corpus_id —
> none of which a retry fixes.

---

## 8. Privacy and data-handling reminders

- **Keep your documents out of the repo tree.** Store them under
  `CORPUS_ROOT` or another personal folder. The `/drop/` path inside
  the repo is gitignored as a convenience, but anything else under the
  repo can be accidentally committed.
- **Do not paste your data into commit messages, run reports, or
  filenames committed back to the repo.** Per the repo `CLAUDE.md`,
  even the *names* of corpus folders or tables can be sensitive
  context.
- **One corpus per use case.** Use distinct `corpus_id`s; do not mix
  unrelated datasets into one corpus. Cleanup is just
  `rm -rf "$CORPUS_ROOT/<corpus-id>"`.
- **API key hygiene.** The `.env` file is gitignored, but it is plain
  text on your laptop. Rotate keys when you finish a piece of work or
  hand the laptop off.

---

## 9. Quick reference — the six MCP tools

| Tool | Reads | Writes | Use when |
|---|---|---|---|
| `list_corpora` | `CORPUS_ROOT` listing | — | First call of a session; verify which corpora exist. |
| `discover_corpus_schema` | A folder or CSV/XLSX file | — *(no corpus mutation)* | Before any structured ingest, to review the proposed relational schema. |
| `ingest_corpus_structured` | A folder + schema | New SQLite tables in `<corpus-id>/corpus.sqlite` | Once the schema is approved. |
| `ingest_corpus_filesystem` | A folder | New chunks + embeddings in `<corpus-id>/corpus.sqlite` | After structured ingest, for unstructured documents. Safe to re-run. |
| `corpus_retrieve` | `<corpus-id>` | — | When you want the raw retrieved chunks for a question (debug / inspection). |
| `corpus_query` | `<corpus-id>` | — | Day-to-day: ask a natural-language question and get an answer with citations. Runs text-to-SQL against structured tables *and* hybrid retrieval against unstructured chunks. |

---

## 10. End-to-end recap

```text
1. git clone … && cd fireflyframework-agentic
2. git checkout -b try/<you>-corpus-demo
3. uv sync
4. cp .env.template .env + edit
5. mkdir -p $CORPUS_ROOT
6. Edit claude_desktop_config.json
7. Restart Claude Desktop
8. In a new Claude Desktop chat:
     - list_corpora                       # see what's there
     - discover_corpus_schema             # review + correct
     - ingest_corpus_structured           # commit the schema
     - ingest_corpus_filesystem           # pick up the rest
     - corpus_query (× N)                 # answer the questions
9. Ask Claude Desktop to produce a Markdown / Word / HTML deliverable.
```

That is the entire loop. Everything else in this guide is
troubleshooting around those nine steps.

---

## 11. (Optional) Contributing changes back via PR

If, while running through this tutorial, you spot a bug or have an
improvement to contribute, the project takes pull requests.

### 11.1 Branch hygiene

You should already be on a working branch (§1.2). If you started from
`main`, switch off it first:

```bash
git checkout main
git pull
git checkout -b fix/<short-descriptive-slug>
# or feat/<...>, docs/<...>, etc.
```

The convention is **never commit directly to `main`** — always work on
a branch and open a PR.

### 11.2 Make the change, run the checks

Edit, then before committing:

```bash
uv run pytest                                  # run the test suite
uv run pre-commit run --all-files              # lint / format
```

Both should pass. The CI runs the same checks.

### 11.3 Commit

```bash
git add <files-you-changed>
git commit -m "docs: short description of what changed and why"
```

A concise commit message that explains the **why** is far more useful
than a list of file changes. Avoid pasting raw output or example data
into commit messages — see the repo `CLAUDE.md` for what to keep out
of git.

### 11.4 Push and open the PR

```bash
git push -u origin <your-branch-name>
gh pr create --fill              # or open the URL printed by `git push`
```

In the PR description, include:

- A one-paragraph summary of what you changed and why.
- A short test plan describing how you verified the change locally.
- Any screenshots / before-after diffs if the change is user-visible.

### 11.5 Review and merge

A maintainer will review. CI must be green and at least one approval is
required before merge. The repo uses squash-merge by default — keep
your branch in a sensible state, but you do not need to clean up
intermediate commits before review.

That is the entire contribution loop. Welcome aboard.
