"""Evaluation judge — async metrics for flyradar and flycanon pipelines.

Every metric: async def metric_name(item: dict, ctx: EvalContext) -> dict | float | None

Flyradar item keys: findings, evidence_index, process_graph, proposed_actions,
  workspace, reports, lexical_missed_ids, nc_items, champion
Flycanon item keys: question, answer, reference, contexts
"""

from __future__ import annotations

import asyncio
import math
import os
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from fireflyframework_agentic.embeddings.providers.ollama import OllamaEmbedder
from fireflyframework_agentic.embeddings.similarity import cosine_similarity
from fireflyframework_agentic.evaluation.judge_client import JudgeClient, same_provider

Metric = Callable[["dict", "EvalContext"], Awaitable["dict | float | None"]]

SYSTEM = "You are a meticulous evaluator of a process-mining discovery report. Return ONLY a JSON object."

SYSTEM_RAG = "You are an evaluator of a RAG system's answers. Return ONLY a JSON object."

RUBRIC = (
    "Score the ANSWER on two metrics:\n"
    "- contains_answer (0.0-1.0): Does the answer contain the correct information from the REFERENCE?\n"
    "- addresses_question (0.0-1.0): Does the answer directly address what the QUESTION is asking?\n"
    'Reply with ONLY {"contains_answer": <float>, "addresses_question": <float>}.'
)


class EvalContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: JudgeClient
    embedder: OllamaEmbedder | None = None
    runs: int = 3


@dataclass
class AdvisoryReport:
    """The G4 output: a plain metrics bag, never a GateResult.

    metrics maps metric-name -> small dict (the per-metric summary).  details
    carries supporting context (counts, ids).  errors lists per-metric failures
    captured by run_judge's best-effort try/except so nothing propagates.
    """

    judge_model: str
    same_provider_caveat: bool
    calibrated: bool  # ALWAYS False for now
    runs: int
    metrics: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ── shared accessors ───────────────────────────────────────────────────────────


def _evidence_index(item: dict) -> dict[str, dict]:
    return {ev.get("id"): ev for ev in item.get("evidence_index", []) if ev.get("id")}


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


def _output_text(item: dict) -> str:
    """All free text the model emitted: finding titles+descriptions + reports."""
    parts: list[str] = []
    for f in item.get("findings", []):
        parts.append(f.get("title", ""))
        parts.append(f.get("description", ""))
    for r in item.get("reports", []):
        parts.append(str(r))
    return "\n".join(p for p in parts if p)


def _workspace_intention(item: dict) -> str:
    ws = item.get("workspace") or {}
    return f"{ws.get('name', '')}\n{ws.get('description', '')}".strip()


def _coerce_float(value, default=None):
    """Coerce a model-returned number/numeric-string to float; total (never raises)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_stem(locator: str) -> str:
    """Return the part before the first '#', or the full string if no '#'."""
    idx = locator.find("#")
    return locator[:idx] if idx != -1 else locator


async def _gather_chat(chat_fn, prompts: list[tuple[str, str]]) -> list[dict]:
    """Run a list of (system, user) prompts concurrently, returning ordered results."""
    results = await asyncio.gather(*[chat_fn(s, u) for s, u in prompts], return_exceptions=True)
    return [r if isinstance(r, dict) else {} for r in results]


# ── [D] DETERMINISTIC — no LLM, always available ────────────────────────────────


async def source_coverage(item: dict, ctx: EvalContext) -> dict:  # noqa: ARG001
    """Distinct source documents cited by >=1 finding vs all source documents.

    Returns {cited, total, orphaned} where orphaned is the sorted list of
    source stems present in evidence_index but cited by no finding.
    """
    ev_idx = _evidence_index(item)
    all_stems = {_source_stem(ev.get("locator", "")) for ev in item.get("evidence_index", []) if ev.get("locator")}
    cited_stems: set[str] = set()
    for f in item.get("findings", []):
        for ref in f.get("evidence_refs", []):
            ev = ev_idx.get(ref.get("evidence_id", ""))
            if ev and ev.get("locator"):
                cited_stems.add(_source_stem(ev["locator"]))
    cited_stems &= all_stems
    orphaned = sorted(all_stems - cited_stems)
    return {"cited": len(cited_stems), "total": len(all_stems), "orphaned": orphaned}


async def excerpt_fill_rate(item: dict, ctx: EvalContext) -> dict:  # noqa: ARG001
    """Fraction of evidence_index entries with a non-empty excerpt.

    Returns {populated, total}.
    """
    entries = item.get("evidence_index", [])
    populated = sum(1 for ev in entries if (ev.get("excerpt") or "").strip())
    return {"populated": populated, "total": len(entries)}


# ── [E] EMBEDDING — needs embedder ───────────────────────────────────────────────


async def semantic_recovery(item: dict, ctx: EvalContext, tau: float = 0.70) -> dict | None:
    """Context-recall: recover lexical misses by embedding similarity.

    Reads item["lexical_missed_ids"] (list of str).
    Returns None if ctx.embedder is None.
    """
    if ctx.embedder is None:
        return None

    lexical_missed_ids: list[str] = item.get("lexical_missed_ids", [])
    missed = set(lexical_missed_ids or [])

    # Build the scored items from nc_items (non-NC = real items for recall)
    # In the new EvalContext model, nc_items is a list of {"id": ..., "description": ...}
    # We treat all item findings as the candidate surface; nc_items stay separate.
    # Recompute as: all items scored = those not in nc_items ids.
    # If there's no registry concept, we use findings as the denominator proxy.
    # But keep the logic simple: just score the missed items against finding descriptions.
    ev_idx = _evidence_index(item)
    candidate_texts: list[str] = []
    for f in item.get("findings", []):
        desc = f.get("description", "")
        if desc:
            candidate_texts.append(desc)
        candidate_texts.extend(_cited_excerpts(f, ev_idx))

    # missed_items: we only know their IDs; we need descriptions to embed.
    # In the new design, if no descriptions available, return minimal result.
    all_findings = item.get("findings", [])
    denom = max(len(all_findings), 1)
    lexical_hits = sum(1 for f in all_findings if f.get("id") not in missed)

    missed_descs: list[tuple[str, str]] = [
        (f.get("id", ""), f.get("description", ""))
        for f in all_findings
        if f.get("id") in missed and f.get("description")
    ]

    if not missed_descs or not candidate_texts:
        recovered_recall = lexical_hits / denom
        return {
            "lexical_recall": round(lexical_hits / denom, 4),
            "recovered_recall": round(recovered_recall, 4),
            "recovered": [],
            "tau": tau,
            "scored_denominator": denom,
        }

    item_texts = [desc for _fid, desc in missed_descs]
    item_vecs = await ctx.embedder._embed_batch(item_texts)
    cand_vecs = await ctx.embedder._embed_batch(candidate_texts)

    recovered: list[dict] = []
    for (fid, _desc), ivec in zip(missed_descs, item_vecs, strict=False):
        best = max((cosine_similarity(ivec, cvec) for cvec in cand_vecs), default=0.0)
        if best >= tau:
            recovered.append({"id": fid, "cosine": round(best, 4)})

    recovered_recall = (lexical_hits + len(recovered)) / denom
    return {
        "lexical_recall": round(lexical_hits / denom, 4),
        "recovered_recall": round(recovered_recall, 4),
        "recovered": recovered,
        "tau": tau,
        "scored_denominator": denom,
    }


# ── [J] JUDGE — needs chat_fn(system, user) -> dict ──────────────────────────────


async def faithfulness(item: dict, ctx: EvalContext) -> dict:
    """Entailment: does each finding's cited evidence SUPPORT its claim?

    Returns {supported, total, unsupported_ids}.
    """
    ev_idx = _evidence_index(item)
    findings = item.get("findings", [])
    cited = [(f, _cited_excerpts(f, ev_idx)) for f in findings]
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
    answers = iter(await _gather_chat(ctx.client.chat_json, prompts))
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


async def numeric_temporal_fidelity(item: dict, ctx: EvalContext) -> dict:
    """Flag numbers/dates asserted in a finding that do NOT match its evidence.

    Returns {mismatches: [{finding_id, value, source}], count}.
    """
    ev_idx = _evidence_index(item)
    scored = [(f, excerpts) for f in item.get("findings", []) if (excerpts := _cited_excerpts(f, ev_idx))]
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
    answers = await _gather_chat(ctx.client.chat_json, prompts)
    mismatches: list[dict] = []
    for (f, _excerpts), answer in zip(scored, answers, strict=False):
        for m in answer.get("mismatches", []) or []:
            mismatches.append(
                {
                    "finding_id": f.get("id", "?"),
                    "value": m.get("value", ""),
                    "source": m.get("source", ""),
                }
            )
    return {"mismatches": mismatches, "count": len(mismatches)}


async def citation_relevance(item: dict, ctx: EvalContext) -> dict:
    """Context precision: fraction of cited passages actually relevant to the claim.

    Returns {precision, relevant, total}.
    """
    ev_idx = _evidence_index(item)
    prompts: list[tuple[str, str]] = []
    for f in item.get("findings", []):
        desc = f.get("description", "")
        for ref in f.get("evidence_refs", []):
            ev = ev_idx.get(ref.get("evidence_id", ""))
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
    answers = await _gather_chat(ctx.client.chat_json, prompts)
    total = len(prompts)
    relevant = sum(1 for a in answers if str(a.get("relevant", "")).lower() == "yes")
    if not total:
        return {"precision": None, "relevant": relevant, "total": total}
    return {"precision": round(relevant / total, 4), "relevant": relevant, "total": total}


async def nc_semantic_precision(item: dict, ctx: EvalContext) -> dict:
    """Count negative-control falsehoods the output asserts or endorses.

    Reads item["nc_items"] as list of {"id": ..., "description": ...} dicts.
    Returns {asserted, total, asserted_ids}.
    """
    output_text = _output_text(item)
    nc_items: list[dict] = item.get("nc_items", [])
    prompts = [
        (
            SYSTEM,
            "Does the OUTPUT assert or endorse the following FALSE statement?\n"
            'Reply with ONLY {"asserted": "yes" or "no"}.\n\n'
            f"FALSE STATEMENT: {nc.get('description', '')}\n"
            f"OUTPUT:\n{output_text}",
        )
        for nc in nc_items
    ]
    answers = await _gather_chat(ctx.client.chat_json, prompts)
    asserted_ids = [
        nc.get("id", "?")
        for nc, a in zip(nc_items, answers, strict=False)
        if str(a.get("asserted", "")).lower() == "yes"
    ]
    return {"asserted": len(asserted_ids), "total": len(nc_items), "asserted_ids": asserted_ids}


async def fabricated_entity(item: dict, ctx: EvalContext) -> dict:
    """Count systems/orgs/metrics named in the output but absent from the corpus.

    Returns {count, entities}.
    """
    output_text = _output_text(item)
    corpus = "\n".join(f"{ev.get('locator', '')} :: {ev.get('excerpt', '')}" for ev in item.get("evidence_index", []))
    user = (
        "List any system, organization, or metric NAMED in the OUTPUT that does NOT "
        "appear anywhere in the CORPUS EVIDENCE.\n"
        'Reply with ONLY {"fabricated": ["<entity>", ...]}.  Empty list if none.\n\n'
        f"OUTPUT:\n{output_text}\n\n"
        f"CORPUS EVIDENCE:\n{corpus}"
    )
    answer = await ctx.client.chat_json(SYSTEM, user)
    entities = answer.get("fabricated", []) or []
    return {"count": len(entities), "entities": list(entities)}


async def contradiction(item: dict, ctx: EvalContext) -> dict:
    """Count internally contradictory finding pairs.

    Returns {count, pairs}.
    """
    lines = []
    for f in item.get("findings", []):
        lines.append(f"{f.get('id', '?')}: {f.get('title', '')} — {f.get('description', '')}")
    user = (
        "Are any two of these FINDINGS mutually contradictory? List each contradicting pair.\n"
        'Reply with ONLY {"pairs": [["<id_a>", "<id_b>"], ...]}.  Empty list if none.\n\n' + "\n".join(lines)
    )
    answer = await ctx.client.chat_json(SYSTEM, user)
    pairs = answer.get("pairs", []) or []
    return {"count": len(pairs), "pairs": [list(p) for p in pairs]}


async def open_gap(item: dict, ctx: EvalContext) -> dict:
    """G-Eval open probe: the most important process issue the output missed.

    Returns {gap} — a free-text advisory narrative (no score).
    """
    pg = item.get("process_graph") or {}
    pg_summary = f"process_graph has {len(pg.get('processes', []))} processes"
    user = (
        "Given this corpus scope and output, what important process issue did the "
        "output FAIL to surface?\n"
        'Reply with ONLY {"gap": "<the most important missed issue, one short paragraph>"}.\n\n'
        f"WORKSPACE SCOPE: {_workspace_intention(item)}\n"
        f"{pg_summary}\n"
        f"OUTPUT:\n{_output_text(item)}"
    )
    answer = await ctx.client.chat_json(SYSTEM, user)
    return {"gap": str(answer.get("gap", ""))}


async def actionability(item: dict, ctx: EvalContext) -> dict:
    """Average 0-1 rating of whether proposed actions are specific+quantified+linked.

    Returns {score, rated}.
    """
    actions = item.get("proposed_actions", []) or []
    finding_ids = {f.get("id") for f in item.get("findings", [])}
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
    answers = await _gather_chat(ctx.client.chat_json, prompts)
    scores: list[float] = []
    for a in answers:
        value = _coerce_float(a.get("score"))
        if value is None:
            continue
        scores.append(value)
    score = round(sum(scores) / len(scores), 4) if scores else None
    return {"score": score, "rated": len(scores)}


async def severity_calibration(item: dict, ctx: EvalContext) -> dict:
    """Per-finding judgment of whether stated severity matches the evidence.

    Returns {miscalibrated, total, verdicts: {finding_id: under|over|calibrated}}.
    """
    ev_idx = _evidence_index(item)
    findings = item.get("findings", [])
    prompts = [
        (
            SYSTEM,
            "Does the STATED SEVERITY match what the CITED EVIDENCE supports?\n"
            'Reply with ONLY {"calibration": "under" or "over" or "calibrated"}.\n\n'
            f"STATED SEVERITY: {f.get('severity', '')}  SCORE: {f.get('score', '')}\n"
            f"FINDING: {f.get('description', '')}\n"
            f"CITED EVIDENCE: {' || '.join(_cited_excerpts(f, ev_idx))}",
        )
        for f in findings
    ]
    answers = await _gather_chat(ctx.client.chat_json, prompts)
    verdicts: dict[str, str] = {}
    miscalibrated = 0
    for f, a in zip(findings, answers, strict=False):
        verdict = str(a.get("calibration", "calibrated")).lower()
        verdicts[f.get("id", "?")] = verdict
        if verdict in ("under", "over"):
            miscalibrated += 1
    return {"miscalibrated": miscalibrated, "total": len(findings), "verdicts": verdicts}


async def answer_relevancy(item: dict, ctx: EvalContext) -> dict:
    """RAGAS-style: does the output address the stated workspace intention?

    Returns {score} in [0,1], or {"score": None} when the vote fails to coerce.
    """
    user = (
        "Does the OUTPUT address the stated WORKSPACE INTENTION (on-topic, responsive)?\n"
        'Reply with ONLY {"score": <number 0-1>}.\n\n'
        f"WORKSPACE INTENTION: {_workspace_intention(item)}\n"
        f"OUTPUT:\n{_output_text(item)}"
    )
    answer = await ctx.client.chat_json(SYSTEM, user)
    return {"score": _coerce_float(answer.get("score"))}


async def surface_deduplication(item: dict, ctx: EvalContext) -> dict:
    """Fraction of near-duplicate process-graph node pairs that are genuinely distinct.

    Returns {distinct, redundant, total, distinct_rate, redundant_pairs}.
    """
    pg = item.get("process_graph", {})
    procs = pg.get("processes", [])

    def _toks(node: dict) -> frozenset[str]:
        return frozenset(node.get("name", "").lower().split())

    per_surface_cap = 10
    candidates: list[tuple[str, dict, dict, str]] = []

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
        for _jac, a, b in pairs[:per_surface_cap]:
            candidates.append(("process", a, b, ""))

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
        for _jac, a, b, proc_name in all_pairs[:per_surface_cap]:
            candidates.append((surface_key, a, b, proc_name))

    if not candidates:
        return {"distinct": 0, "redundant": 0, "total": 0, "distinct_rate": None, "redundant_pairs": []}

    prompts = []
    for surface, a, b, parent_proc in candidates:
        ctx_line = f"\nPARENT PROCESS: {parent_proc}\n" if parent_proc else ""
        prompts.append(
            (
                SYSTEM,
                f"Are these two {surface} nodes genuinely DISTINCT process concepts, or is one a "
                f"duplicate / sub-case / restatement of the other?\n"
                f"{ctx_line}"
                'Reply with ONLY {"verdict": "DISTINCT" or "DUPLICATE", "reason": "<one line>"}.\n\n'
                f"{surface.upper()} A: {a.get('name', '')} — {a.get('description', '')}\n"
                f"{surface.upper()} B: {b.get('name', '')} — {b.get('description', '')}",
            )
        )

    answers = await _gather_chat(ctx.client.chat_json, prompts)

    distinct = 0
    redundant = 0
    redundant_pairs: list[dict] = []
    for (surface, a, b, _parent), answer in zip(candidates, answers, strict=False):
        verdict = str(answer.get("verdict", "")).upper()
        if verdict == "DISTINCT":
            distinct += 1
        else:
            redundant += 1
            redundant_pairs.append(
                {
                    "surface": surface,
                    "a": a.get("name", ""),
                    "b": b.get("name", ""),
                    "reason": str(answer.get("reason", "")),
                }
            )

    total = distinct + redundant
    return {
        "distinct": distinct,
        "redundant": redundant,
        "total": total,
        "distinct_rate": round(distinct / total, 4) if total else None,
        "redundant_pairs": redundant_pairs,
    }


async def comparative_vs_champion(item: dict, ctx: EvalContext) -> dict | None:
    """Pairwise MT-Bench-style review of candidate vs champion (advisory only).

    Returns None if item["champion"] is not present.
    Returns {candidate, champion, more_consistent}.
    """
    champion = item.get("champion")
    if champion is None:
        return None
    user = (
        "Score the CANDIDATE and the CHAMPION outputs on five axes (1-5 each): "
        "Coverage, Quality, Evidence, Actionability, Regression.  Then say which is "
        "more internally consistent.\n"
        "Reply with ONLY "
        '{"candidate": {"coverage": x, "quality": x, "evidence": x, "actionability": x, "regression": x}, '
        '"champion": {"coverage": x, "quality": x, "evidence": x, "actionability": x, "regression": x}, '
        '"more_consistent": "candidate" or "champion"}.\n\n'
        f"CANDIDATE:\n{_output_text(item)}\n\n"
        f"CHAMPION:\n{_output_text(champion)}"
    )
    out = await ctx.client.chat_json(SYSTEM, user)
    return {
        "candidate": out.get("candidate", {}),
        "champion": out.get("champion", {}),
        "more_consistent": out.get("more_consistent", ""),
    }


# ── flycanon custom metrics ───────────────────────────────────────────────────────


async def _rag_score_once(item: dict, ctx: EvalContext) -> dict | None:
    """Single RAG scoring call: returns {"contains_answer": float, "addresses_question": float}."""
    question = item.get("question", "")
    reference = item.get("reference", "")
    answer = item.get("answer", "")
    if not question or not answer:
        return None
    user = f"QUESTION: {question}\nREFERENCE: {reference}\nANSWER: {answer}\n\n{RUBRIC}"
    result = await ctx.client.chat_json(SYSTEM_RAG, user)
    return result


async def contains_answer(item: dict, ctx: EvalContext) -> float | None:
    """Flycanon: does the answer contain the correct information from the reference?

    Runs ctx.runs times and returns the median score.
    Returns None if the item lacks question/answer.
    """
    scores: list[float] = []
    for _ in range(max(1, ctx.runs)):
        result = await _rag_score_once(item, ctx)
        if result is None:
            return None
        val = _coerce_float(result.get("contains_answer"))
        if val is not None:
            scores.append(val)
    if not scores:
        return None
    return round(statistics.median(scores), 4)


async def addresses_question(item: dict, ctx: EvalContext) -> float | None:
    """Flycanon: does the answer directly address what the question is asking?

    Runs ctx.runs times and returns the median score.
    Returns None if the item lacks question/answer.
    """
    scores: list[float] = []
    for _ in range(max(1, ctx.runs)):
        result = await _rag_score_once(item, ctx)
        if result is None:
            return None
        val = _coerce_float(result.get("addresses_question"))
        if val is not None:
            scores.append(val)
    if not scores:
        return None
    return round(statistics.median(scores), 4)


# ── RAGAS metrics ─────────────────────────────────────────────────────────────────
# ragas/langchain imports are inline inside _sync() since ragas is optional.


def _make_ragas_sample(item: dict):
    """Build a RAGAS SingleTurnSample from an item dict (ragas import inline)."""
    from ragas import SingleTurnSample  # type: ignore[import]  # noqa: PLC0415

    return SingleTurnSample(
        user_input=item.get("question", ""),
        response=item.get("answer", ""),
        reference=item.get("reference", ""),
        retrieved_contexts=item.get("contexts", []),
    )


def _make_ragas_llm(ctx: EvalContext):
    """Build a LangChain LLM wrapper for RAGAS (langchain import inline)."""
    provider, model = ctx.client.provider, ctx.client.model
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # type: ignore[import]  # noqa: PLC0415

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        return ChatAnthropic(model=model, api_key=api_key, temperature=0.0)
    if provider in ("openai", "azure"):
        from langchain_openai import ChatOpenAI  # type: ignore[import]  # noqa: PLC0415

        api_key = os.environ.get("OPENAI_API_KEY", "")
        return ChatOpenAI(model=model, api_key=api_key, temperature=0.0)
    if provider == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore[import]  # noqa: PLC0415

        return ChatOllama(model=model, temperature=0.0)
    raise ValueError(f"RAGAS: unsupported provider {provider!r}")


def _make_ragas_embeddings(ctx: EvalContext):
    """Build LangChain embeddings for RAGAS (langchain import inline)."""
    if ctx.embedder is not None:
        from langchain_ollama import OllamaEmbeddings  # type: ignore[import]  # noqa: PLC0415

        return OllamaEmbeddings(model=ctx.embedder._model)
    from langchain_anthropic import AnthropicEmbeddings  # type: ignore[import]  # noqa: PLC0415

    return AnthropicEmbeddings()


async def _ragas_score(metric_name: str, item: dict, ctx: EvalContext) -> float | None:
    """Run a single named RAGAS metric and return its float score (or None)."""

    def _sync():
        from ragas import evaluate  # type: ignore[import]  # noqa: PLC0415
        from ragas.dataset_schema import EvaluationDataset  # type: ignore[import]  # noqa: PLC0415
        from ragas.metrics import (  # type: ignore[import]  # noqa: PLC0415
            AnswerCorrectness,
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )

        _metrics_map = {
            "answer_correctness": AnswerCorrectness,
            "answer_relevancy_ragas": AnswerRelevancy,
            "ragas_faithfulness": Faithfulness,
            "context_recall": ContextRecall,
            "context_precision": ContextPrecision,
        }
        metric_cls = _metrics_map.get(metric_name)
        if metric_cls is None:
            return None

        llm = _make_ragas_llm(ctx)
        embeddings = _make_ragas_embeddings(ctx)
        metric = metric_cls(llm=llm, embeddings=embeddings)
        sample = _make_ragas_sample(item)
        dataset = EvaluationDataset(samples=[sample])
        result = evaluate(dataset=dataset, metrics=[metric])
        df = result.to_pandas()
        col = df.columns[df.columns.str.contains(metric_name.replace("_ragas", ""), case=False)]
        if col.empty:
            return None
        val = df[col[0]].iloc[0]
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return round(float(val), 4)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


async def answer_correctness(item: dict, ctx: EvalContext) -> float | None:
    """RAGAS answer correctness (semantic F1 against reference)."""
    return await _ragas_score("answer_correctness", item, ctx)


async def ragas_faithfulness(item: dict, ctx: EvalContext) -> float | None:
    """RAGAS faithfulness (answer grounded in retrieved contexts)."""
    return await _ragas_score("ragas_faithfulness", item, ctx)


async def context_recall(item: dict, ctx: EvalContext) -> float | None:
    """RAGAS context recall (reference coverage by retrieved contexts)."""
    return await _ragas_score("context_recall", item, ctx)


async def context_precision(item: dict, ctx: EvalContext) -> float | None:
    """RAGAS context precision (retrieved contexts relevant to the question)."""
    return await _ragas_score("context_precision", item, ctx)


# ── median-of-N helpers ──────────────────────────────────────────────────────────


def _numeric_leaves(d: dict) -> dict[tuple, float]:
    """Flatten a metric dict to {path: float} over its FLOAT score-leaves only."""
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
    """Median across N metric-dicts: FLOAT score-leaves -> per-key median; rest = first."""
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


async def run_judge(
    item: dict,
    ctx: EvalContext,
    *,
    pipeline_model: str = "",
) -> AdvisoryReport:
    """Run all metrics concurrently and return an AdvisoryReport.

    Best-effort: never raises. Failing metrics append to report.errors.
    """
    report = AdvisoryReport(
        judge_model=ctx.client.model_spec,
        same_provider_caveat=same_provider(pipeline_model, ctx.client.model_spec),
        calibrated=False,
        runs=ctx.runs,
    )

    # [D] deterministic (no LLM)
    det_metrics: list[tuple[str, Metric]] = [
        ("source_coverage", source_coverage),
        ("excerpt_fill_rate", excerpt_fill_rate),
    ]
    # [E] embedding
    emb_metrics: list[tuple[str, Metric]] = [
        ("semantic_recovery", semantic_recovery),
    ]
    # [J] judge metrics (median-of-runs handled externally for single-call ones)
    judge_metrics: list[tuple[str, Metric]] = [
        ("faithfulness", faithfulness),
        ("numeric_temporal_fidelity", numeric_temporal_fidelity),
        ("citation_relevance", citation_relevance),
        ("nc_semantic_precision", nc_semantic_precision),
        ("fabricated_entity", fabricated_entity),
        ("contradiction", contradiction),
        ("open_gap", open_gap),
        ("actionability", actionability),
        ("severity_calibration", severity_calibration),
        ("answer_relevancy", answer_relevancy),
        ("surface_deduplication", surface_deduplication),
        ("comparative_vs_champion", comparative_vs_champion),
    ]
    # flycanon custom
    flycanon_metrics: list[tuple[str, Metric]] = [
        ("contains_answer", contains_answer),
        ("addresses_question", addresses_question),
    ]
    # RAGAS
    ragas_metrics: list[tuple[str, Metric]] = [
        ("answer_correctness", answer_correctness),
        ("ragas_faithfulness", ragas_faithfulness),
        ("context_recall", context_recall),
        ("context_precision", context_precision),
    ]

    all_metrics = det_metrics + emb_metrics + judge_metrics + flycanon_metrics + ragas_metrics

    async def _run_one(name: str, fn: Metric) -> None:
        try:
            result = await fn(item, ctx)
            if result is not None:
                report.metrics[name] = result
        except Exception as exc:
            report.errors.append(f"{name}: {type(exc).__name__}: {exc}")

    await asyncio.gather(*[_run_one(name, fn) for name, fn in all_metrics])
    return report
