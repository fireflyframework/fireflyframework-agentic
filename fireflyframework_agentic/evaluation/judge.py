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

"""G4 — LLM-as-a-Judge: an opt-in, NON-BLOCKING, NON-DETERMINISTIC advisory gate.

G4 NEVER affects the PROMOTE/HOLD verdict and NEVER raises into the caller.
run_judge() wraps every metric in try/except; a failing metric appends to
report.errors and the run continues (best-effort).  The result is an
AdvisoryReport, NOT a GateResult — it is carried separately so it can never
enter verdict() or the Skipped tuple (see scorecard / verdict_unaffected_note).

Three families of metric (matching the flyradar contracts):
- [D] DETERMINISTIC — pure python, no LLM, printed even when the judge is off:
      source_coverage, excerpt_fill_rate.
- [E] EMBEDDING — needs an embed_fn (local Ollama BGE by default):
      semantic_recovery (context recall).
- [J] JUDGE — needs a chat_fn(system, user) -> dict; each [J] metric instructs
      the model to reply with ONLY JSON: faithfulness, numeric_temporal_fidelity,
      citation_relevance, nc_semantic_precision, fabricated_entity, contradiction,
      open_gap, actionability, severity_calibration, answer_relevancy,
      comparative_vs_champion.

Aggregation follows the flycanon custom-judge design: run each [J] metric `runs`
times and take the MEDIAN of its numeric scores (robust to an outlier vote).

Zero new dependencies: stdlib (json, statistics) + numpy.  All imports at top.
calibrated is ALWAYS False for now (LLM-as-a-Judge calibration is §14, future work).
"""

from __future__ import annotations

import concurrent.futures
import statistics
from dataclasses import dataclass, field

import numpy as np

from fireflyframework_agentic.evaluation.judge_client import (
    JudgeClient,
    OllamaEmbedder,
    cosine,
    same_provider,
)
from fireflyframework_agentic.evaluation.matcher import source_stem

SYSTEM = "You are a meticulous evaluator of a process-mining discovery report. Return ONLY a JSON object."


@dataclass
class AdvisoryReport:
    """The G4 output: a plain metrics bag, never a GateResult.

    metrics maps metric-name -> small dict (the per-metric summary).  details
    carries supporting context (counts, ids).  errors lists per-metric failures
    captured by run_judge's best-effort try/except so nothing propagates.
    """

    judge_model: str
    same_provider_caveat: bool
    calibrated: bool  # ALWAYS False for now (§14)
    runs: int
    metrics: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ── shared accessors ───────────────────────────────────────────────────────────


def _evidence_index(result: dict) -> dict[str, dict]:
    return {ev.get("id"): ev for ev in result.get("evidence_index", []) if ev.get("id")}


def _cited_excerpts(finding: dict, evidence_index: dict[str, dict]) -> list[str]:
    """Excerpts of the evidence a finding cites (via evidence_refs.evidence_id)."""
    out: list[str] = []
    for ref in finding.get("evidence_refs", []):
        ev = evidence_index.get(ref.get("evidence_id", ""))
        if ev:
            excerpt = ev.get("excerpt") or ""
            if excerpt:
                out.append(excerpt)
    return out


def _output_text(result: dict) -> str:
    """All free text the model emitted: finding titles+descriptions + reports."""
    parts: list[str] = []
    for f in result.get("findings", []):
        parts.append(f.get("title", ""))
        parts.append(f.get("description", ""))
    for r in result.get("reports", []):
        parts.append(str(r))
    return "\n".join(p for p in parts if p)


def _workspace_intention(result: dict) -> str:
    ws = result.get("workspace") or {}
    return f"{ws.get('name', '')}\n{ws.get('description', '')}".strip()


def _coerce_float(value, default=None):
    """Coerce a model-returned number/numeric-string to float; total (never raises).

    Returns ``default`` (None) on junk so one malformed vote drops that single
    vote instead of discarding the whole metric.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _map_chat(chat_fn, prompts, workers=1):
    """Run a list of (system, user) chat prompts, returning ordered result dicts.

    ``workers <= 1`` calls ``chat_fn`` SEQUENTIALLY — byte-for-byte identical to
    the in-line loops it replaces, INCLUDING letting a raise propagate (so
    run_judge's per-metric try/except still drops that whole metric, the
    behaviour the suite locks in).

    ``workers >= 2`` fans the calls out across a ThreadPoolExecutor while
    PRESERVING input order in the returned list.  Concurrency cannot let one
    raising future poison the batch, so in that path a raising call's slot
    becomes ``{}`` — the metric's aggregation degrades for that one vote but
    never raises (the same best-effort contract as run_judge).
    """
    prompts = list(prompts)
    if workers <= 1:
        return [chat_fn(system, user) for system, user in prompts]

    results: list[dict] = [{} for _ in prompts]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(chat_fn, system, user): idx
            for idx, (system, user) in enumerate(prompts)
        }
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:  # best-effort: a dropped vote, never a raise
                results[idx] = {}
    return results


# ── [D] DETERMINISTIC — no LLM, always available ────────────────────────────────


def source_coverage(result: dict) -> dict:
    """Distinct source documents cited by >=1 finding vs all source documents.

    Returns {cited, total, orphaned} where orphaned is the sorted list of
    source stems present in evidence_index but cited by no finding.
    """
    evidence_index = _evidence_index(result)
    all_stems = {
        source_stem(ev.get("locator", ""))
        for ev in result.get("evidence_index", [])
        if ev.get("locator")
    }
    cited_stems: set[str] = set()
    for f in result.get("findings", []):
        for ref in f.get("evidence_refs", []):
            ev = evidence_index.get(ref.get("evidence_id", ""))
            if ev and ev.get("locator"):
                cited_stems.add(source_stem(ev["locator"]))
    cited_stems &= all_stems
    orphaned = sorted(all_stems - cited_stems)
    return {"cited": len(cited_stems), "total": len(all_stems), "orphaned": orphaned}


def excerpt_fill_rate(result: dict) -> dict:
    """Fraction of evidence_index entries with a non-empty excerpt.

    Returns {populated, total}.  This is the signal behind older runs' low G3
    grounding: empty excerpts cannot ground anything.
    """
    entries = result.get("evidence_index", [])
    populated = sum(1 for ev in entries if (ev.get("excerpt") or "").strip())
    return {"populated": populated, "total": len(entries)}


# ── [E] EMBEDDING — needs embed_fn ───────────────────────────────────────────────


def semantic_recovery(
    result: dict,
    registry,
    lexical_missed_ids: list[str],
    embed_fn,
    tau: float = 0.70,
) -> dict:
    """Context-recall: recover G2 lexical misses by embedding similarity.

    For each registry item flagged a LEXICAL MISS by G2, embed its
    description+keywords and take the max cosine against the embeddings of every
    finding description (and their cited excerpts).  If max cosine >= tau the
    item is counted semantically present (recovered).

    recovered_recall = (lexical_hits + recovered) / scored_denominator, where
    the scored denominator is the count of non-NC items scored by G2 (real
    items, matching G2's recall denominator family).  Returns the lexical recall,
    the recovered recall, the recovered item list (with cosine), and tau.
    """
    missed = set(lexical_missed_ids or [])
    real_items = registry.real_items
    scored_items = [i for i in real_items if i.tier != "L3"]
    denom = len(scored_items) or 1
    lexical_hits = sum(1 for i in scored_items if i.id not in missed)

    # Candidate texts the findings actually surfaced.
    evidence_index = _evidence_index(result)
    candidate_texts: list[str] = []
    for f in result.get("findings", []):
        desc = f.get("description", "")
        if desc:
            candidate_texts.append(desc)
        candidate_texts.extend(_cited_excerpts(f, evidence_index))

    missed_items = [i for i in scored_items if i.id in missed]
    if not missed_items or not candidate_texts:
        recovered_recall = lexical_hits / denom
        return {
            "lexical_recall": round(lexical_hits / denom, 4),
            "recovered_recall": round(recovered_recall, 4),
            "recovered": [],
            "tau": tau,
            "scored_denominator": denom,
        }

    item_texts = [f"{i.description} {' '.join(i.keywords)}".strip() for i in missed_items]
    item_vecs = np.asarray(embed_fn(item_texts), dtype=np.float64)
    cand_vecs = np.asarray(embed_fn(candidate_texts), dtype=np.float64)

    recovered: list[dict] = []
    for item, ivec in zip(missed_items, item_vecs):
        best = max((cosine(ivec, cvec) for cvec in cand_vecs), default=0.0)
        if best >= tau:
            recovered.append({"id": item.id, "cosine": round(best, 4)})

    recovered_recall = (lexical_hits + len(recovered)) / denom
    return {
        "lexical_recall": round(lexical_hits / denom, 4),
        "recovered_recall": round(recovered_recall, 4),
        "recovered": recovered,
        "tau": tau,
        "scored_denominator": denom,
    }


# ── [J] JUDGE — needs chat_fn(system, user) -> dict ──────────────────────────────


def faithfulness(result: dict, chat_fn, *, workers: int = 1) -> dict:
    """Entailment: does each finding's cited evidence SUPPORT its claim?

    Per (finding, cited-excerpts) pair, ask SUPPORTED / NOT_SUPPORTED.  Returns
    {supported, total, unsupported_ids}.  Findings with no cited evidence are
    counted as not-supported (nothing to entail against).
    """
    evidence_index = _evidence_index(result)
    findings = result.get("findings", [])
    cited = [(f, _cited_excerpts(f, evidence_index)) for f in findings]
    prompts = [
        (
            SYSTEM,
            "Does the cited evidence span ENTAIL the claim made in this finding?\n"
            'Reply with ONLY {"verdict": "SUPPORTED" or "NOT_SUPPORTED", "reason": "<one line>"}.\n\n'
            f"FINDING: {f.get('description', '')}\n"
            f"CITED EVIDENCE: {' || '.join(excerpts)}",
        )
        for f, excerpts in cited
        if excerpts
    ]
    answers = iter(_map_chat(chat_fn, prompts, workers))
    supported = 0
    unsupported_ids: list[str] = []
    for f, excerpts in cited:
        fid = f.get("id", "?")
        if not excerpts:
            unsupported_ids.append(fid)
            continue
        verdict = str(next(answers).get("verdict", "")).upper()
        if verdict == "SUPPORTED":
            supported += 1
        else:
            unsupported_ids.append(fid)
    return {"supported": supported, "total": len(findings), "unsupported_ids": unsupported_ids}


def numeric_temporal_fidelity(result: dict, chat_fn, *, workers: int = 1) -> dict:
    """Flag numbers/dates asserted in a finding that do NOT match its evidence.

    Closes the 45-days-vs-3-days gap.  Returns {mismatches: [{finding_id, value,
    source}], count}.
    """
    evidence_index = _evidence_index(result)
    scored = [
        (f, excerpts)
        for f in result.get("findings", [])
        if (excerpts := _cited_excerpts(f, evidence_index))
    ]
    prompts = [
        (
            SYSTEM,
            "List every specific number or date asserted in the FINDING that does "
            "NOT match the CITED EVIDENCE.\n"
            'Reply with ONLY {"mismatches": [{"value": "<claimed>", "source": "<what the evidence says>"}]}. '
            "Empty list if all match.\n\n"
            f"FINDING: {f.get('description', '')}\n"
            f"CITED EVIDENCE: {' || '.join(excerpts)}",
        )
        for f, excerpts in scored
    ]
    answers = _map_chat(chat_fn, prompts, workers)
    mismatches: list[dict] = []
    for (f, _excerpts), answer in zip(scored, answers):
        for m in answer.get("mismatches", []) or []:
            mismatches.append(
                {
                    "finding_id": f.get("id", "?"),
                    "value": m.get("value", ""),
                    "source": m.get("source", ""),
                }
            )
    return {"mismatches": mismatches, "count": len(mismatches)}


def citation_relevance(result: dict, chat_fn, *, workers: int = 1) -> dict:
    """Context precision: fraction of cited passages actually relevant to the claim.

    Per evidence_ref, ask yes/no relevance.  precision = relevant / total_refs.
    Returns {precision, relevant, total}; when total == 0 (no cited passages with
    excerpts) precision is None — the kept ``total`` lets a reader tell "perfect"
    apart from "nothing to score".
    """
    evidence_index = _evidence_index(result)
    prompts: list[tuple[str, str]] = []
    for f in result.get("findings", []):
        desc = f.get("description", "")
        for ref in f.get("evidence_refs", []):
            ev = evidence_index.get(ref.get("evidence_id", ""))
            if not ev:
                continue
            excerpt = ev.get("excerpt") or ""
            if not excerpt:
                continue
            prompts.append(
                (
                    SYSTEM,
                    "Is this cited passage actually relevant to / used by this claim?\n"
                    'Reply with ONLY {"relevant": "yes" or "no"}.\n\n'
                    f"CLAIM: {desc}\n"
                    f"CITED PASSAGE: {excerpt}",
                )
            )
    answers = _map_chat(chat_fn, prompts, workers)
    total = len(prompts)
    relevant = sum(1 for a in answers if str(a.get("relevant", "")).lower() == "yes")
    if not total:
        return {"precision": None, "relevant": relevant, "total": total}
    return {"precision": round(relevant / total, 4), "relevant": relevant, "total": total}


def nc_semantic_precision(result: dict, registry, chat_fn, *, workers: int = 1) -> dict:
    """Count negative-control falsehoods the output asserts or endorses.

    Per NC item, ask yes/no whether the output endorses the false statement.
    Returns {asserted, total, asserted_ids}.  The semantic counterpart to the
    inert deterministic NC check.
    """
    output_text = _output_text(result)
    nc_items = registry.nc_items
    prompts = [
        (
            SYSTEM,
            "Does the OUTPUT assert or endorse the following FALSE statement?\n"
            'Reply with ONLY {"asserted": "yes" or "no"}.\n\n'
            f"FALSE STATEMENT: {item.description}\n"
            f"OUTPUT:\n{output_text}",
        )
        for item in nc_items
    ]
    answers = _map_chat(chat_fn, prompts, workers)
    asserted_ids = [
        item.id for item, a in zip(nc_items, answers) if str(a.get("asserted", "")).lower() == "yes"
    ]
    return {"asserted": len(asserted_ids), "total": len(nc_items), "asserted_ids": asserted_ids}


def fabricated_entity(result: dict, chat_fn) -> dict:
    """Count systems/orgs/metrics named in the output but absent from the corpus.

    Returns {count, entities}.  The corpus universe is the set of evidence
    excerpts + locators.
    """
    output_text = _output_text(result)
    corpus = "\n".join(
        f"{ev.get('locator', '')} :: {ev.get('excerpt', '')}"
        for ev in result.get("evidence_index", [])
    )
    user = (
        "List any system, organization, or metric NAMED in the OUTPUT that does NOT "
        "appear anywhere in the CORPUS EVIDENCE.\n"
        'Reply with ONLY {"fabricated": ["<entity>", ...]}.  Empty list if none.\n\n'
        f"OUTPUT:\n{output_text}\n\n"
        f"CORPUS EVIDENCE:\n{corpus}"
    )
    entities = chat_fn(SYSTEM, user).get("fabricated", []) or []
    return {"count": len(entities), "entities": list(entities)}


def contradiction(result: dict, chat_fn) -> dict:
    """Count internally contradictory finding pairs.

    Returns {count, pairs}.  pairs is the list of contradicting finding-id pairs
    the judge reports.
    """
    lines = []
    for f in result.get("findings", []):
        lines.append(f"{f.get('id', '?')}: {f.get('title', '')} — {f.get('description', '')}")
    user = (
        "Are any two of these FINDINGS mutually contradictory? List each contradicting pair.\n"
        'Reply with ONLY {"pairs": [["<id_a>", "<id_b>"], ...]}.  Empty list if none.\n\n'
        + "\n".join(lines)
    )
    pairs = chat_fn(SYSTEM, user).get("pairs", []) or []
    return {"count": len(pairs), "pairs": [list(p) for p in pairs]}


def open_gap(result: dict, chat_fn) -> dict:
    """G-Eval open probe: the most important process issue the output missed.

    Returns {gap} — a free-text advisory narrative (no score).
    """
    pg = result.get("process_graph") or {}
    pg_summary = f"process_graph has {len(pg.get('processes', []))} processes"
    user = (
        "Given this corpus scope and output, what important process issue did the "
        "output FAIL to surface?\n"
        'Reply with ONLY {"gap": "<the most important missed issue, one short paragraph>"}.\n\n'
        f"WORKSPACE SCOPE: {_workspace_intention(result)}\n"
        f"{pg_summary}\n"
        f"OUTPUT:\n{_output_text(result)}"
    )
    return {"gap": str(chat_fn(SYSTEM, user).get("gap", ""))}


def actionability(result: dict, chat_fn, *, workers: int = 1) -> dict:
    """Average 0-1 rating of whether proposed actions are specific+quantified+linked.

    Returns {score, rated}.  Each action is rated against whether it is specific,
    quantified, and linked to a finding.
    """
    actions = result.get("proposed_actions", []) or []
    finding_ids = {f.get("id") for f in result.get("findings", [])}
    prompts = [
        (
            SYSTEM,
            "Rate whether this proposed action is SPECIFIC, QUANTIFIED, and LINKED to a "
            "finding.\n"
            'Reply with ONLY {"score": <number 0-1>}.\n\n'
            f"TITLE: {a.get('title', '')}\n"
            f"DESCRIPTION: {a.get('description', '')}\n"
            f"OWNER: {a.get('owner_persona', '')}  HORIZON: {a.get('horizon', '')}  "
            f"LEVER: {a.get('lever', '')}  EFFORT: {a.get('effort', '')}\n"
            f"EXPECTED_SAVINGS_FTE: {a.get('expected_savings_fte', '')}  "
            f"EXPECTED_SAVINGS_USD: {a.get('expected_savings_usd', '')}\n"
            f"LINKED_TO_FINDING: {a.get('finding_id') in finding_ids}",
        )
        for a in actions
    ]
    answers = _map_chat(chat_fn, prompts, workers)
    scores: list[float] = []
    for a in answers:
        value = _coerce_float(a.get("score"))
        if value is None:  # malformed vote -> skip this action, keep the metric
            continue
        scores.append(value)
    score = round(sum(scores) / len(scores), 4) if scores else None
    return {"score": score, "rated": len(scores)}


def severity_calibration(result: dict, chat_fn, *, workers: int = 1) -> dict:
    """Per-finding judgment of whether stated severity matches the evidence.

    Returns {miscalibrated, total, verdicts: {finding_id: under|over|calibrated}}.
    """
    evidence_index = _evidence_index(result)
    findings = result.get("findings", [])
    prompts = [
        (
            SYSTEM,
            "Does the STATED SEVERITY match what the CITED EVIDENCE supports?\n"
            'Reply with ONLY {"calibration": "under" or "over" or "calibrated"}.\n\n'
            f"STATED SEVERITY: {f.get('severity', '')}  SCORE: {f.get('score', '')}\n"
            f"FINDING: {f.get('description', '')}\n"
            f"CITED EVIDENCE: {' || '.join(_cited_excerpts(f, evidence_index))}",
        )
        for f in findings
    ]
    answers = _map_chat(chat_fn, prompts, workers)
    verdicts: dict[str, str] = {}
    miscalibrated = 0
    for f, a in zip(findings, answers):
        verdict = str(a.get("calibration", "calibrated")).lower()
        verdicts[f.get("id", "?")] = verdict
        if verdict in ("under", "over"):
            miscalibrated += 1
    return {"miscalibrated": miscalibrated, "total": len(findings), "verdicts": verdicts}


def answer_relevancy(result: dict, chat_fn) -> dict:
    """RAGAS-style: does the output address the stated workspace intention?

    Returns {score} in [0,1], or {"score": None} when the vote fails to coerce.
    """
    user = (
        "Does the OUTPUT address the stated WORKSPACE INTENTION (on-topic, responsive)?\n"
        'Reply with ONLY {"score": <number 0-1>}.\n\n'
        f"WORKSPACE INTENTION: {_workspace_intention(result)}\n"
        f"OUTPUT:\n{_output_text(result)}"
    )
    return {"score": _coerce_float(chat_fn(SYSTEM, user).get("score"))}


def surface_deduplication(result: dict, chat_fn, *, workers: int = 1) -> dict:
    """Fraction of near-duplicate process-graph node pairs that are genuinely distinct.

    Scoping rules:
    - Processes: all pairs compared (cross-process is valid at this level).
    - Activities and decisions: ONLY within the same parent process.  The same
      activity name appearing in two different processes is a legitimate repetition
      (e.g. "Approve Request" in both Loan and Credit-Card flows), not a duplicate.

    For each surface, the top-10 most name-similar pairs (token-Jaccard >= 0.30)
    are selected.  For activities/decisions the parent process name is included in
    the judge prompt so it can reason about intra-process context.  30 pairs total.

    Returns {distinct, redundant, total, distinct_rate, redundant_pairs}.
    """
    pg = result.get("process_graph", {})
    procs = pg.get("processes", [])

    def _toks(node: dict) -> frozenset[str]:
        return frozenset(node.get("name", "").lower().split())

    PER_SURFACE_CAP = 10
    # candidates: (surface, node_a, node_b, parent_process_name)
    candidates: list[tuple[str, dict, dict, str]] = []

    # Processes: compare all pairs
    if len(procs) >= 2:
        pairs: list[tuple[float, dict, dict]] = []
        for i in range(len(procs)):
            for j in range(i + 1, len(procs)):
                a_t, b_t = _toks(procs[i]), _toks(procs[j])
                union = a_t | b_t
                if not union:
                    continue
                jac = len(a_t & b_t) / len(union)
                if jac >= 0.30:
                    pairs.append((jac, procs[i], procs[j]))
        pairs.sort(key=lambda x: x[0], reverse=True)
        for _jac, a, b in pairs[:PER_SURFACE_CAP]:
            candidates.append(("process", a, b, ""))

    # Activities and decisions: within the same parent process only
    for surface_key, attr in (("activity", "activities"), ("decision", "decisions")):
        all_pairs: list[tuple[float, dict, dict, str]] = []
        for proc in procs:
            nodes = proc.get(attr, [])
            proc_name = proc.get("name", "")
            if len(nodes) < 2:
                continue
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    a_t, b_t = _toks(nodes[i]), _toks(nodes[j])
                    union = a_t | b_t
                    if not union:
                        continue
                    jac = len(a_t & b_t) / len(union)
                    if jac >= 0.30:
                        all_pairs.append((jac, nodes[i], nodes[j], proc_name))
        all_pairs.sort(key=lambda x: x[0], reverse=True)
        for _jac, a, b, proc_name in all_pairs[:PER_SURFACE_CAP]:
            candidates.append((surface_key, a, b, proc_name))

    if not candidates:
        return {"distinct": 0, "redundant": 0, "total": 0, "distinct_rate": None, "redundant_pairs": []}

    prompts = []
    for surface, a, b, parent_proc in candidates:
        ctx = f"\nPARENT PROCESS: {parent_proc}\n" if parent_proc else ""
        prompts.append((
            SYSTEM,
            f"Are these two {surface} nodes genuinely DISTINCT process concepts, or is one a "
            f"duplicate / sub-case / restatement of the other?\n"
            f"{ctx}"
            'Reply with ONLY {"verdict": "DISTINCT" or "DUPLICATE", "reason": "<one line>"}.\n\n'
            f"{surface.upper()} A: {a.get('name', '')} — {a.get('description', '')}\n"
            f"{surface.upper()} B: {b.get('name', '')} — {b.get('description', '')}",
        ))

    answers = _map_chat(chat_fn, prompts, workers)

    distinct = 0
    redundant = 0
    redundant_pairs: list[dict] = []
    for (surface, a, b, _parent), answer in zip(candidates, answers):
        verdict = str(answer.get("verdict", "")).upper()
        if verdict == "DISTINCT":
            distinct += 1
        else:
            redundant += 1
            redundant_pairs.append({
                "surface": surface,
                "a": a.get("name", ""),
                "b": b.get("name", ""),
                "reason": str(answer.get("reason", "")),
            })

    total = distinct + redundant
    return {
        "distinct": distinct,
        "redundant": redundant,
        "total": total,
        "distinct_rate": round(distinct / total, 4) if total else None,
        "redundant_pairs": redundant_pairs,
    }


def comparative_vs_champion(result: dict, champion_result: dict, chat_fn) -> dict:
    """Pairwise MT-Bench-style review of candidate vs champion (advisory only).

    Returns {candidate, champion, more_consistent} where candidate/champion are
    1-5 ratings on Coverage/Quality/Evidence/Actionability/Regression.  Never
    feeds G5.
    """
    user = (
        "Score the CANDIDATE and the CHAMPION outputs on five axes (1-5 each): "
        "Coverage, Quality, Evidence, Actionability, Regression.  Then say which is "
        "more internally consistent.\n"
        "Reply with ONLY "
        '{"candidate": {"coverage": x, "quality": x, "evidence": x, "actionability": x, "regression": x}, '
        '"champion": {"coverage": x, "quality": x, "evidence": x, "actionability": x, "regression": x}, '
        '"more_consistent": "candidate" or "champion"}.\n\n'
        f"CANDIDATE:\n{_output_text(result)}\n\n"
        f"CHAMPION:\n{_output_text(champion_result)}"
    )
    out = chat_fn(SYSTEM, user)
    return {
        "candidate": out.get("candidate", {}),
        "champion": out.get("champion", {}),
        "more_consistent": out.get("more_consistent", ""),
    }


# ── median-of-N for [J] metrics ──────────────────────────────────────────────────


def _numeric_leaves(d: dict) -> dict[tuple, float]:
    """Flatten a metric dict to {path: float} over its FLOAT score-leaves only.

    Median applies to continuous scores only.  A leaf counts as numeric-for-median
    only when its value is a ``float``; ``bool`` and ``int`` leaves (counts,
    denominators, 1-5 axes, and other bookkeeping) are deliberately skipped and
    taken from the first run unchanged — this avoids fractional counts (rated=0.5)
    and count/len(list) disagreement under runs>1 with an even N.
    """
    out: dict[tuple, float] = {}

    def walk(node, path: tuple) -> None:
        if isinstance(node, float):
            out[path] = node
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + (k,))

    walk(d, ())
    return out


def _set_leaf(d: dict, path: tuple, value: float) -> None:
    node = d
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _median_runs(samples: list[dict]) -> dict:
    """Median across N metric-dicts: FLOAT score-leaves -> per-key median; rest = first.

    Only continuous float scores are medianed; integer bookkeeping (counts,
    denominators, 1-5 axes) and all non-numeric fields are taken from the first run.
    """
    samples = [s for s in samples if isinstance(s, dict)]
    if not samples:
        return {}
    base = samples[0]
    if len(samples) == 1:
        return base
    leaf_values: dict[tuple, list[float]] = {}
    for s in samples:
        for path, val in _numeric_leaves(s).items():
            leaf_values.setdefault(path, []).append(val)
    merged = dict(base)
    for path, vals in leaf_values.items():
        try:
            _set_leaf(merged, path, round(statistics.median(vals), 4))
        except (KeyError, TypeError):
            continue
    return merged


# ── orchestrator ─────────────────────────────────────────────────────────────────


def run_judge(
    result: dict,
    registry,
    *,
    judge_model: str,
    runs: int = 1,
    concurrency: int = 1,
    pipeline_model: str = "",
    champion_result: dict | None = None,
    chat_fn=None,
    embed_fn=None,
    tau: float = 0.70,
    lexical_missed_ids: list[str] | None = None,
) -> AdvisoryReport:
    """Run the G4 advisory gate, best-effort.  NEVER raises; NEVER affects verdict.

    If chat_fn / embed_fn are None, real ones are built from JudgeClient /
    OllamaEmbedder (tests inject stubs instead).  Each [J] metric runs `runs`
    times and the median of its numeric scores is kept.  Every metric is wrapped
    in try/except: a failure appends to report.errors and the run continues.

    ``concurrency`` (opt-in, default 1) bounds the per-item [J] metrics' internal
    fan-out: 1 keeps the sequential per-item loops; >=2 runs each metric's items
    across a thread pool (order preserved).  The median-of-N ``runs`` loop stays
    sequential and the single-call metrics are unaffected.  The result is
    byte-for-byte identical at concurrency=1.

    Returns an AdvisoryReport (a plain dict carrier) with calibrated=False and
    same_provider_caveat = same_provider(pipeline_model, judge_model).
    """
    if chat_fn is None:
        client = JudgeClient(judge_model)
        chat_fn = client.chat_json
    if embed_fn is None:
        embed_fn = OllamaEmbedder().embed

    report = AdvisoryReport(
        judge_model=judge_model,
        same_provider_caveat=same_provider(pipeline_model, judge_model),
        calibrated=False,
        runs=runs,
    )

    def _run_det(name: str, fn) -> None:
        try:
            report.metrics[name] = fn()
        except Exception as exc:  # best-effort: never raise
            report.errors.append(f"{name}: {type(exc).__name__}: {exc}")

    def _run_judge_metric(name: str, fn) -> None:
        try:
            samples = [fn() for _ in range(max(1, runs))]
            report.metrics[name] = _median_runs(samples)
        except Exception as exc:  # best-effort: never raise
            report.errors.append(f"{name}: {type(exc).__name__}: {exc}")

    # [D] deterministic — always computed, no LLM.
    _run_det("source_coverage", lambda: source_coverage(result))
    _run_det("excerpt_fill_rate", lambda: excerpt_fill_rate(result))

    # [E] embedding — context recall.
    _run_det(
        "semantic_recovery",
        lambda: semantic_recovery(result, registry, lexical_missed_ids or [], embed_fn, tau=tau),
    )

    # [J] judge — median-of-N.  Per-item metrics fan out at workers=concurrency.
    _run_judge_metric("faithfulness", lambda: faithfulness(result, chat_fn, workers=concurrency))
    _run_judge_metric(
        "numeric_temporal_fidelity",
        lambda: numeric_temporal_fidelity(result, chat_fn, workers=concurrency),
    )
    _run_judge_metric(
        "citation_relevance", lambda: citation_relevance(result, chat_fn, workers=concurrency)
    )
    _run_judge_metric(
        "nc_semantic_precision",
        lambda: nc_semantic_precision(result, registry, chat_fn, workers=concurrency),
    )
    _run_judge_metric("fabricated_entity", lambda: fabricated_entity(result, chat_fn))
    _run_judge_metric("contradiction", lambda: contradiction(result, chat_fn))
    _run_judge_metric("open_gap", lambda: open_gap(result, chat_fn))
    _run_judge_metric("actionability", lambda: actionability(result, chat_fn, workers=concurrency))
    _run_judge_metric(
        "severity_calibration",
        lambda: severity_calibration(result, chat_fn, workers=concurrency),
    )
    _run_judge_metric("answer_relevancy", lambda: answer_relevancy(result, chat_fn))
    _run_judge_metric(
        "surface_deduplication",
        lambda: surface_deduplication(result, chat_fn, workers=concurrency),
    )
    if champion_result is not None:
        _run_judge_metric(
            "comparative_vs_champion",
            lambda: comparative_vs_champion(result, champion_result, chat_fn),
        )

    return report
