# Spec 11 — QA Diagnoser Sub-Agent

**Date:** 2026-05-04
**Status:** Draft — MVP2 backlog (not approved)
**Owner:** Agentic Factory MVP2
**Depends on:** Spec 10 (deployer in place — diagnoser is most valuable for runtime failures); Spec 3 qa agent stable.
**Required by:** higher first-pass success rate of the QA loop; shorter iteration counts on real-world intents.

---

## Context

In MVP1 the qa agent's `diagnose_failure` is a heuristic Python callable: it classifies failures into a small enum (`compile_error`, `test_assertion`, `network`, `timeout`, `unknown`) using regex over test outputs. That is enough to surface "what kind of failure" but not enough to tell codegen *what to change next*. A failed assertion in `tests/test_query.py:42` could be caused by the chunker, the embedder, or the synthesise step — heuristics can't tell.

This spec extracts diagnosis into a dedicated LLM-backed sub-agent, `qa_diagnoser`, that the qa agent invokes when:

- The heuristic classifier returns `unknown`, OR
- The same test ID has failed in ≥ 2 consecutive iterations (the classifier didn't help codegen converge).

The diagnoser collects multi-source evidence (logs, screenshots, stack traces, distributed traces, db snapshots when available), reasons about the most likely root cause, and emits structured `QAFeedback` that codegen can act on directly.

## Non-goals

- Replacing the heuristic classifier. The classifier still runs first; the diagnoser is a fallback for hard failures.
- A full APM. Reuse existing `FireflyTracer` traces and runner logs; do not deploy new observability infra.
- Auto-fixing. Diagnoser proposes; codegen disposes.

## Sketch

- New module `factory.agents.qa_diagnoser` — Claude Sonnet, `ReflexionPattern` (hypothesis → critique → finalize). Tools: `tail_logs`, `read_artifact`, `parse_trace`, `screenshot_describe` (vision), `knowledge_search`.
- New `EvidencePack` Pydantic model: `logs: list[LogChunk]`, `traces: list[TraceSpan]`, `screenshots: list[bytes]`, `failed_tests: list[TestFailure]`, `recent_diff: str` (the codegen patch from the last iteration).
- The qa agent's `diagnose_failure` callable becomes `diagnose_failure_v2`: runs the heuristic first, returns its result if confident; otherwise builds the `EvidencePack`, calls `qa_diagnoser.run(evidence)`, and merges the response into `QAReport.failures[*].diagnosis`.
- The diagnoser is **not** a separate workflow — it runs inside the qa action so the iteration counter and budget are unchanged.

## Output schema

```python
class Diagnosis(BaseModel):
    hypothesis: str
    confidence: Literal["low", "medium", "high"]
    supporting_evidence: list[str]    # references into EvidencePack
    affected_files: list[str]
    suggested_change: str             # natural-language; codegen translates to a patch
    rejected_hypotheses: list[str]    # what the diagnoser considered and ruled out
```

## Verification

- A fixture EvidencePack with a known failure mode (e.g., off-by-one in a chunker boundary) → diagnoser identifies the chunker, not the embedder, with `confidence=high`.
- A fixture with truly insufficient evidence → diagnoser returns `confidence=low` and lists what additional evidence would help (drives a future "evidence-gathering" sub-step).
- The qa_diagnoser does not run when the heuristic classifier returns `confidence=high` — verified by tracking tool-call counts in tests.

## Open questions

- Vision tools (screenshots) require Claude with vision capability and add cost. Should we gate vision behind a config flag? Probably yes — many backends (a service with no UI) don't need it.
- The diagnoser is most useful with distributed traces, which generated apps may not emit by default. Should the codegen agent's archetypes include OpenTelemetry instrumentation by default? Spec proposes yes; it's cheap insurance.
- Diagnoser cost can blow up for hard failures. Need a per-iteration diagnoser budget separate from codegen's budget.
