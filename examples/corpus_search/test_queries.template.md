# Corpus Search — Test Query Template

Operators evaluating their own corpus copy this file to
`examples/corpus_search/test_queries.md` (gitignored) and replace the
placeholder content below with questions grounded in their own
documents. The non-template `.md` is intentionally kept out of git so
no specific corpus / customer references leak.

The grading harness (`/tmp/run_query_battery.py` or your equivalent)
parses the YAML block(s); each entry needs an ID, a question, an
optional list of expected source paths to check citations against,
and a free-form list of pass criteria the human reviewer evaluates.

Recommended question mix (pick what fits the corpus):

- factual lookup, single doc — baseline retrieval health check
- synthesis across multiple docs — exercises RRF + reranker fusion
- date / number — exercises BM25 morphology + tokenisation
- cross-language — question in language A, source in language B;
  forces vector retrieval to do real work
- tabular — question whose answer is in an XLSX-converted markdown
  table; exercises the markitdown extraction quality
- negative control — fact NOT in the corpus; the answer should
  acknowledge the gap honestly without fabricating a number

```yaml
- id: q01
  kind: factual_lookup
  language: en  # or pt-BR, es, fr, …
  category: <your-corpus-category>
  question: "Replace with a question grounded in one of your documents."
  expected_source_paths:
    - "drop/<your-folder>/<expected-doc>.pdf"
  pass_criteria:
    - "answer mentions <key fact you read in the doc>"
    - "at least one citation chunk_id resolves to expected_source_paths"

- id: q10
  kind: negative_control
  language: en
  category: out-of-corpus
  question: "Ask something you know your corpus does NOT contain."
  expected_source_paths: []
  pass_criteria:
    - "answer text explicitly acknowledges the corpus does not contain the requested data (e.g. 'do not contain', 'don't have enough information', 'not provided')"
    - "answer must NOT fabricate a specific value"
    - "any citations that ARE present must resolve to real chunks (no hallucinated chunk_ids); tangential-but-honestly-cited context is acceptable"
```

## Privacy

The non-template file is in `.gitignore` so the operator's questions —
which inevitably reveal which corpus they are evaluating — never end
up in version control. Treat it as you would a `.env` file: keep it
local, share via secure channels if collaborating.
