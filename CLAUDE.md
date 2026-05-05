# CLAUDE.md — Repo-specific guidance

## Avoid data leaks via git

When evaluating examples (especially `examples/corpus_search/`) against an
operator-supplied corpus, **never commit anything that names or describes the
specific corpus content**. The risk is that filenames, folder labels, sample
question text, query results, and run reports reveal *which corpus the
operator was running against* — which itself reveals customer / engagement
context, even if the underlying documents are individually public.

### What to keep out of git

| Artefact | Treat as |
|---|---|
| `./drop/` and any sibling local-corpus folder | already gitignored under `/drop/`; never `git add -f` it |
| Per-operator question banks (`examples/corpus_search/test_queries.md`) | gitignored — operators copy from `test_queries.template.md` |
| Per-run reports under `docs/superpowers/specs/*-run-report.md` | gitignored — keep locally, don't commit |
| Per-run results JSON under `docs/superpowers/specs/*-query-results.json` | gitignored |
| Spec docs / READMEs that reference an operator's specific corpus | sanitise before commit — describe the *pattern*, not the *instance* |
| Comment text or test fixture text that names the operator's regulator / agency / company | replace with generic placeholders ("the regulator", "agency", "Acme Corp") |
| Commit messages and commit titles | review for the same leaks before pushing |

### Pattern to follow

For any committed file that *describes* an evaluation:

1. Talk about the *shape* of the corpus, not the contents (e.g. "multi-format
   corpus, ~50 PDFs + spreadsheets" — not "<industry>-<region> research"
   strings that pin the engagement).
2. Reference test bank patterns via committed `*.template.md` files and keep
   the populated `*.md` gitignored.
3. Run-time artefacts (per-doc latency tables, per-query answer text,
   citation lists) stay out of version control entirely.
4. When sanitising existing committed files, run a final
   `git ls-files | xargs grep -l <corpus-name-or-folder>` to catch stragglers.

### Gitignore baseline

The repo already gitignores:

```
/drop/
/kg/
/runs/
examples/corpus_search/test_queries.md
examples/corpus_search/test_queries.local.md
docs/superpowers/specs/*-run-report.md
docs/superpowers/specs/*-query-results.json
```

Don't weaken these without a clear reason and a sanitisation plan for
whatever is being moved into version control.

### Why this matters

Even when every individual document in a corpus is publicly available, the
*selection* of which documents an operator ingested is engagement-specific
context. A future maintainer reading the repo should learn the framework's
patterns from the test-bank template — not which customer was being served.

---

## Other repo conventions

(Add other standing instructions here as they accumulate. Keep this file
focused on rules that apply across sessions; transient context belongs in
plans / specs.)
