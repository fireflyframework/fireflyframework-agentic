"""Evaluation judge — async metrics for flyradar and flycanon pipelines.

Every metric: async def metric_name(item: dict, ctx: EvalContext) -> dict | None
Each result is {"score": float | None, **extra} — read result["score"] for the headline.

Flyradar item keys: findings, evidence_index, process_graph, proposed_actions,
  workspace, reports, lexical_missed_ids, nc_items, champion
Flycanon item keys: question, answer, reference, contexts
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.embeddings.base import BaseEmbedder
from fireflyframework_agentic.embeddings.similarity import cosine_similarity

# ── judge client ─────────────────────────────────────────────────────────────────

_AGENT_NAME = "evaluation-judge"


def parse_model(spec: str) -> tuple[str, str]:
    """Split "provider:model" -> (provider, model). Bare spec -> ("unknown", spec)."""
    spec = (spec or "").strip()
    if ":" not in spec:
        return "unknown", spec
    provider, model = spec.split(":", 1)
    return provider.strip().lower(), model.strip()


def same_provider(pipeline_model: str, judge_model: str) -> bool:
    """True iff both specs share the same known provider prefix."""
    p, _ = parse_model(pipeline_model)
    j, _ = parse_model(judge_model)
    if p == "unknown" or j == "unknown":
        return False
    return p == j


class JudgeClient:
    """Async multi-provider judge backed by :class:`FireflyAgent`.

    Each ``judge`` call returns a validated instance of the requested pydantic
    ``output_type`` — schema enforcement replaces hand-rolled JSON parsing.
    ``temperature`` is pinned to 0.0 for deterministic verdicts. Agents are built
    lazily and cached per ``(system, output_type, max_tokens)``; transient
    rate-limit / 5xx errors and output-validation failures are retried by
    FireflyAgent / pydantic-ai (``max_retries``). The provider reads its API key
    when the agent is first built, so constructing a client never needs a secret.
    """

    def __init__(self, model: str, timeout: int = 120, max_retries: int = 3) -> None:
        self.model_spec = model
        self.provider, self.model = parse_model(model)
        self.timeout = timeout
        self.max_retries = max_retries
        self._agents: dict[tuple[str, type, int], FireflyAgent] = {}

    def _agent[T: BaseModel](self, system: str, output_type: type[T], max_tokens: int) -> FireflyAgent:
        key = (system, output_type, max_tokens)
        agent = self._agents.get(key)
        if agent is None:
            agent = FireflyAgent(
                name=_AGENT_NAME,
                model=self.model_spec,
                instructions=system,
                output_type=output_type,
                model_settings={"temperature": 0.0, "max_tokens": max_tokens},
                retries=self.max_retries,
                auto_register=False,
            )
            self._agents[key] = agent
        return agent

    async def judge[T: BaseModel](self, system: str, user: str, output_type: type[T], max_tokens: int = 1024) -> T:
        """Send (system, user) to the model and return a validated ``output_type``.

        Raises on exhausted retries / unknown provider / output that cannot be
        coerced to ``output_type`` — callers must not treat a failure as a verdict.
        """
        agent = self._agent(system, output_type, max_tokens)
        result = await agent.run(user, timeout=self.timeout)
        return result.output


Metric = Callable[["dict", "EvalContext"], Awaitable["dict | None"]]

SYSTEM = "You are a meticulous evaluator of a process-mining discovery report. Return ONLY a JSON object."

SYSTEM_RAG = "You are an evaluator of a RAG system's answers. Return ONLY a JSON object."

RUBRIC = (
    "Score the ANSWER on two metrics:\n"
    "- contains_answer (0.0-1.0): Does the answer contain the correct information from the REFERENCE?\n"
    "- addresses_question (0.0-1.0): Does the answer directly address what the QUESTION is asking?\n"
    'Reply with ONLY {"contains_answer": <float>, "addresses_question": <float>}.'
)

# ── structured judge outputs (validated by the model via FireflyAgent) ───────────


class _Verdict(BaseModel):
    verdict: str = ""
    reason: str = ""


class _Mismatch(BaseModel):
    value: str = ""
    source: str = ""


class _Mismatches(BaseModel):
    mismatches: list[_Mismatch] = []


class _Relevant(BaseModel):
    relevant: str = ""


class _Asserted(BaseModel):
    asserted: str = ""


class _Fabricated(BaseModel):
    fabricated: list[str] = []


class _Pairs(BaseModel):
    pairs: list[list[str]] = []


class _Gap(BaseModel):
    gap: str = ""


class _Score(BaseModel):
    score: float | None = None


class _Calibration(BaseModel):
    calibration: str = "calibrated"


class _Comparison(BaseModel):
    candidate: dict = {}
    champion: dict = {}
    more_consistent: str = ""


class _RagScore(BaseModel):
    contains_answer: float | None = None
    addresses_question: float | None = None


class EvalContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: JudgeClient
    embedder: BaseEmbedder | None = None


class AdvisoryReport(BaseModel):
    """Aggregated output of :func:`run_judge`: a plain metrics bag.

    metrics maps metric-name -> the per-metric result (a small dict or float).
    errors lists per-metric failures captured by run_judge's best-effort
    try/except so nothing propagates.  judge_model is run metadata;
    same_provider_caveat flags self-grading risk (the judge shares the evaluated
    pipeline's provider).
    """

    judge_model: str
    same_provider_caveat: bool
    metrics: dict = {}
    errors: list[str] = []


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


def _source_stem(locator: str) -> str:
    """Return the part before the first '#', or the full string if no '#'."""
    idx = locator.find("#")
    return locator[:idx] if idx != -1 else locator


async def _judge_all[T: BaseModel](ctx: EvalContext, system: str, users: list[str], output_type: type[T]) -> list[T]:
    """Judge a list of user prompts concurrently against one system prompt.

    Failures propagate (no swallowing into a fake verdict): a failed call raises,
    so run_judge records it in report.errors instead of scoring it as a result.
    """
    return list(await asyncio.gather(*[ctx.client.judge(system, u, output_type) for u in users]))


def _scored(score: float | None, **extra: object) -> dict:
    """Uniform metric result: a leading ``score`` float (or None) then structured extras.

    Every metric returns this shape so results compare apples-to-apples — read
    ``result["score"]`` for the headline number and the remaining keys for the breakdown.
    ``score`` is None for metrics with no natural [0, 1] aggregate (pure defect counts and
    free-text probes).
    """
    return {"score": score, **extra}


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
    return _scored(
        round(len(cited_stems) / len(all_stems), 4) if all_stems else None,
        cited=len(cited_stems),
        total=len(all_stems),
        orphaned=orphaned,
    )


async def excerpt_fill_rate(item: dict, ctx: EvalContext) -> dict:  # noqa: ARG001
    """Fraction of evidence_index entries with a non-empty excerpt.

    Returns {populated, total}.
    """
    entries = item.get("evidence_index", [])
    populated = sum(1 for ev in entries if (ev.get("excerpt") or "").strip())
    return _scored(round(populated / len(entries), 4) if entries else None, populated=populated, total=len(entries))


# ── [E] EMBEDDING — needs embedder ───────────────────────────────────────────────


async def semantic_recovery(item: dict, ctx: EvalContext, tau: float = 0.70) -> dict | None:
    """Must-find recall: a lexical baseline lifted by a vector pass (the hybrid).

    Upstream, the eval harness matches the expected ("must-find") items against the
    discovery output by surface/keyword (lexical) matching; the ids it could NOT match
    arrive here as ``item["lexical_missed_ids"]``. This metric runs a second, *vector*
    pass over those misses: it embeds each missed item and the candidate finding texts
    and counts it recovered when the best cosine similarity is >= ``tau``. The three
    recall views make the lexical -> vector -> hybrid progression explicit:

      - ``score``            : hybrid recall — lexical hits PLUS vector recoveries.
      - ``lexical_recall``   : lexical-only baseline.
      - ``vector_recovered`` : the misses the vector pass recovered, each with its cosine.

    Returns None when ``ctx.embedder`` is unset (the vector pass needs embeddings).
    """
    if ctx.embedder is None:
        return None

    missed = set(item.get("lexical_missed_ids", []) or [])

    # Candidate surface the vector pass scores against: finding descriptions plus
    # their cited evidence excerpts.
    ev_idx = _evidence_index(item)
    candidate_texts: list[str] = []
    for f in item.get("findings", []):
        desc = f.get("description", "")
        if desc:
            candidate_texts.append(desc)
        candidate_texts.extend(_cited_excerpts(f, ev_idx))

    all_findings = item.get("findings", [])
    denom = max(len(all_findings), 1)
    lexical_hits = sum(1 for f in all_findings if f.get("id") not in missed)

    # The lexical misses we can embed (those carrying a description).
    missed_descs: list[tuple[str, str]] = [
        (f.get("id", ""), f.get("description", ""))
        for f in all_findings
        if f.get("id") in missed and f.get("description")
    ]

    if not missed_descs or not candidate_texts:
        lexical_recall = round(lexical_hits / denom, 4)
        return _scored(
            lexical_recall,
            lexical_recall=lexical_recall,
            vector_recovered=[],
            tau=tau,
            scored_denominator=denom,
        )

    item_vecs = await ctx.embedder._embed_batch([desc for _fid, desc in missed_descs])
    cand_vecs = await ctx.embedder._embed_batch(candidate_texts)

    vector_recovered: list[dict] = []
    for (fid, _desc), ivec in zip(missed_descs, item_vecs, strict=False):
        best = max((cosine_similarity(ivec, cvec) for cvec in cand_vecs), default=0.0)
        if best >= tau:
            vector_recovered.append({"id": fid, "cosine": round(best, 4)})

    return _scored(
        round((lexical_hits + len(vector_recovered)) / denom, 4),
        lexical_recall=round(lexical_hits / denom, 4),
        vector_recovered=vector_recovered,
        tau=tau,
        scored_denominator=denom,
    )


# ── [J] JUDGE — needs ctx.client.judge(system, user, output_type) ────────────────


async def faithfulness(item: dict, ctx: EvalContext) -> dict:
    """Per-finding entailment: does each finding's CITED evidence support its claim?

    Custom-rubric judge over a discovery report. For every finding it gathers the excerpts
    the finding explicitly cites (evidence_refs -> evidence_index) and asks the LLM a single
    binary verdict — does that cited evidence ENTAIL the finding's claim (SUPPORTED /
    NOT_SUPPORTED)? A finding that cites no evidence is counted unsupported without an LLM
    call. The unit judged is the whole finding, compared only against its own citations.

    Returns {score, supported, total, unsupported_ids}; score = supported / total.

    Differs from ``ragas_faithfulness`` (which measures the same hallucination concept):
    that one works on a RAG answer — it decomposes the ANSWER into atomic claims and scores
    the fraction inferable from the retrieved ``contexts`` (not citations), returning a
    single float in [0, 1]. Use this one for per-finding SUPPORTED/NOT_SUPPORTED
    accountability when findings carry explicit citations.
    """
    ev_idx = _evidence_index(item)
    findings = item.get("findings", [])
    cited = [(f, _cited_excerpts(f, ev_idx)) for f in findings]
    users = [
        "Does the cited evidence span ENTAIL the claim made in this finding?\n"
        'Reply with ONLY {"verdict": "SUPPORTED" or "NOT_SUPPORTED", "reason": "<one line>"}.\n\n'
        f"FINDING: {f.get('description', '')}\n"
        f"CITED EVIDENCE: {' || '.join(excerpts)}"
        for f, excerpts in cited
        if excerpts
    ]
    answers = iter(await _judge_all(ctx, SYSTEM, users, _Verdict))
    supported = 0
    unsupported_ids: list[str] = []
    for f, excerpts in cited:
        fid = f.get("id", "?")
        if not excerpts:
            unsupported_ids.append(fid)
            continue
        if str(next(answers).verdict).upper() == "SUPPORTED":
            supported += 1
        else:
            unsupported_ids.append(fid)
    return _scored(
        round(supported / len(findings), 4) if findings else None,
        supported=supported,
        total=len(findings),
        unsupported_ids=unsupported_ids,
    )


async def numeric_temporal_fidelity(item: dict, ctx: EvalContext) -> dict:
    """Flag numbers/dates asserted in a finding that do NOT match its evidence.

    Returns {score, mismatches: [{finding_id, value, source}], count}; score is the fraction
    of evidence-cited findings with no numeric/temporal mismatch (None if none were scored).
    """
    ev_idx = _evidence_index(item)
    scored = [(f, excerpts) for f in item.get("findings", []) if (excerpts := _cited_excerpts(f, ev_idx))]
    users = [
        "List every specific number or date asserted in the FINDING that does "
        "NOT match the CITED EVIDENCE.\n"
        'Reply with ONLY {"mismatches": [{"value": "<claimed>", "source": "<what the evidence says>"}]}. '
        "Empty list if all match.\n\n"
        f"FINDING: {f.get('description', '')}\n"
        f"CITED EVIDENCE: {' || '.join(excerpts)}"
        for f, excerpts in scored
    ]
    answers = await _judge_all(ctx, SYSTEM, users, _Mismatches)
    mismatches: list[dict] = []
    for (f, _excerpts), answer in zip(scored, answers, strict=False):
        for m in answer.mismatches:
            mismatches.append(
                {
                    "finding_id": f.get("id", "?"),
                    "value": m.value,
                    "source": m.source,
                }
            )
    bad = len({m["finding_id"] for m in mismatches})
    return _scored(
        round(1 - bad / len(scored), 4) if scored else None,
        mismatches=mismatches,
        count=len(mismatches),
    )


async def citation_relevance(item: dict, ctx: EvalContext) -> dict:
    """Context precision: fraction of cited passages actually relevant to the claim.

    Returns {score, relevant, total}; score is that precision (relevant / total).
    """
    ev_idx = _evidence_index(item)
    users: list[str] = []
    for f in item.get("findings", []):
        desc = f.get("description", "")
        for ref in f.get("evidence_refs", []):
            ev = ev_idx.get(ref.get("evidence_id", ""))
            if not ev:
                continue
            excerpt = ev.get("excerpt") or ""
            if not excerpt:
                continue
            users.append(
                "Is this cited passage actually relevant to / used by this claim?\n"
                'Reply with ONLY {"relevant": "yes" or "no"}.\n\n'
                f"CLAIM: {desc}\n"
                f"CITED PASSAGE: {excerpt}"
            )
    answers = await _judge_all(ctx, SYSTEM, users, _Relevant)
    total = len(users)
    relevant = sum(1 for a in answers if str(a.relevant).lower() == "yes")
    return _scored(round(relevant / total, 4) if total else None, relevant=relevant, total=total)


async def nc_semantic_precision(item: dict, ctx: EvalContext) -> dict:
    """Count negative-control falsehoods the output asserts or endorses.

    Reads item["nc_items"] as list of {"id": ..., "description": ...} dicts.
    Returns {score, asserted, total, asserted_ids}; score is the fraction of negative
    controls NOT endorsed (1 - asserted / total) — higher is better.
    """
    output_text = _output_text(item)
    nc_items: list[dict] = item.get("nc_items", [])
    users = [
        "Does the OUTPUT assert or endorse the following FALSE statement?\n"
        'Reply with ONLY {"asserted": "yes" or "no"}.\n\n'
        f"FALSE STATEMENT: {nc.get('description', '')}\n"
        f"OUTPUT:\n{output_text}"
        for nc in nc_items
    ]
    answers = await _judge_all(ctx, SYSTEM, users, _Asserted)
    asserted_ids = [
        nc.get("id", "?") for nc, a in zip(nc_items, answers, strict=False) if str(a.asserted).lower() == "yes"
    ]
    return _scored(
        round(1 - len(asserted_ids) / len(nc_items), 4) if nc_items else None,
        asserted=len(asserted_ids),
        total=len(nc_items),
        asserted_ids=asserted_ids,
    )


async def fabricated_entity(item: dict, ctx: EvalContext) -> dict:
    """Count systems/orgs/metrics named in the output but absent from the corpus.

    Returns {score, count, entities}; score is None (a pure defect count has no denominator).
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
    answer = await ctx.client.judge(SYSTEM, user, _Fabricated)
    entities = answer.fabricated
    return _scored(None, count=len(entities), entities=list(entities))


async def contradiction(item: dict, ctx: EvalContext) -> dict:
    """Count internally contradictory finding pairs.

    Returns {score, count, pairs}; score is None (a pure defect count has no denominator).
    """
    lines = []
    for f in item.get("findings", []):
        lines.append(f"{f.get('id', '?')}: {f.get('title', '')} — {f.get('description', '')}")
    user = (
        "Are any two of these FINDINGS mutually contradictory? List each contradicting pair.\n"
        'Reply with ONLY {"pairs": [["<id_a>", "<id_b>"], ...]}.  Empty list if none.\n\n' + "\n".join(lines)
    )
    answer = await ctx.client.judge(SYSTEM, user, _Pairs)
    pairs = answer.pairs
    return _scored(None, count=len(pairs), pairs=[list(p) for p in pairs])


async def open_gap(item: dict, ctx: EvalContext) -> dict:
    """G-Eval open probe: the most important process issue the output missed.

    Returns {score, gap}; score is None (free-text advisory narrative, no score).
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
    answer = await ctx.client.judge(SYSTEM, user, _Gap)
    return _scored(None, gap=str(answer.gap))


async def actionability(item: dict, ctx: EvalContext) -> dict:
    """Average 0-1 rating of whether proposed actions are specific+quantified+linked.

    Returns {score, rated}.
    """
    actions = item.get("proposed_actions", []) or []
    finding_ids = {f.get("id") for f in item.get("findings", [])}
    users = [
        "Rate whether this proposed action is SPECIFIC, QUANTIFIED, and LINKED to a "
        "finding.\n"
        'Reply with ONLY {"score": <number 0-1>}.\n\n'
        f"TITLE: {a.get('title', '')}\n"
        f"DESCRIPTION: {a.get('description', '')}\n"
        f"OWNER: {a.get('owner_persona', '')}  HORIZON: {a.get('horizon', '')}  "
        f"LEVER: {a.get('lever', '')}  EFFORT: {a.get('effort', '')}\n"
        f"EXPECTED_SAVINGS_FTE: {a.get('expected_savings_fte', '')}  "
        f"EXPECTED_SAVINGS_USD: {a.get('expected_savings_usd', '')}\n"
        f"LINKED_TO_FINDING: {a.get('finding_id') in finding_ids}"
        for a in actions
    ]
    answers = await _judge_all(ctx, SYSTEM, users, _Score)
    scores = [a.score for a in answers if a.score is not None]
    score = round(sum(scores) / len(scores), 4) if scores else None
    return _scored(score, rated=len(scores))


async def severity_calibration(item: dict, ctx: EvalContext) -> dict:
    """Per-finding judgment of whether stated severity matches the evidence.

    Returns {score, miscalibrated, total, verdicts: {finding_id: under|over|calibrated}};
    score is the fraction of findings whose severity is calibrated (1 - miscalibrated / total).
    """
    ev_idx = _evidence_index(item)
    findings = item.get("findings", [])
    users = [
        "Does the STATED SEVERITY match what the CITED EVIDENCE supports?\n"
        'Reply with ONLY {"calibration": "under" or "over" or "calibrated"}.\n\n'
        f"STATED SEVERITY: {f.get('severity', '')}  SCORE: {f.get('score', '')}\n"
        f"FINDING: {f.get('description', '')}\n"
        f"CITED EVIDENCE: {' || '.join(_cited_excerpts(f, ev_idx))}"
        for f in findings
    ]
    answers = await _judge_all(ctx, SYSTEM, users, _Calibration)
    verdicts: dict[str, str] = {}
    miscalibrated = 0
    for f, a in zip(findings, answers, strict=False):
        verdict = str(a.calibration).lower()
        verdicts[f.get("id", "?")] = verdict
        if verdict in ("under", "over"):
            miscalibrated += 1
    return _scored(
        round(1 - miscalibrated / len(findings), 4) if findings else None,
        miscalibrated=miscalibrated,
        total=len(findings),
        verdicts=verdicts,
    )


async def answer_relevancy(item: dict, ctx: EvalContext) -> dict:
    """RAGAS-style: does the output address the stated workspace intention?

    Returns {score} in [0,1] (score is None when the vote fails to coerce).
    """
    user = (
        "Does the OUTPUT address the stated WORKSPACE INTENTION (on-topic, responsive)?\n"
        'Reply with ONLY {"score": <number 0-1>}.\n\n'
        f"WORKSPACE INTENTION: {_workspace_intention(item)}\n"
        f"OUTPUT:\n{_output_text(item)}"
    )
    answer = await ctx.client.judge(SYSTEM, user, _Score)
    return _scored(answer.score)


async def surface_deduplication(item: dict, ctx: EvalContext) -> dict:
    """Fraction of near-duplicate process-graph node pairs that are genuinely distinct.

    Returns {score, distinct, redundant, total, redundant_pairs}; score is the distinct rate
    (distinct / total), None when there were no near-duplicate candidates to judge.
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
        return _scored(None, distinct=0, redundant=0, total=0, redundant_pairs=[])

    users = []
    for surface, a, b, parent_proc in candidates:
        ctx_line = f"\nPARENT PROCESS: {parent_proc}\n" if parent_proc else ""
        users.append(
            f"Are these two {surface} nodes genuinely DISTINCT process concepts, or is one a "
            f"duplicate / sub-case / restatement of the other?\n"
            f"{ctx_line}"
            'Reply with ONLY {"verdict": "DISTINCT" or "DUPLICATE", "reason": "<one line>"}.\n\n'
            f"{surface.upper()} A: {a.get('name', '')} — {a.get('description', '')}\n"
            f"{surface.upper()} B: {b.get('name', '')} — {b.get('description', '')}"
        )

    answers = await _judge_all(ctx, SYSTEM, users, _Verdict)

    distinct = 0
    redundant = 0
    redundant_pairs: list[dict] = []
    for (surface, a, b, _parent), answer in zip(candidates, answers, strict=False):
        verdict = str(answer.verdict).upper()
        if verdict == "DISTINCT":
            distinct += 1
        else:
            redundant += 1
            redundant_pairs.append(
                {
                    "surface": surface,
                    "a": a.get("name", ""),
                    "b": b.get("name", ""),
                    "reason": str(answer.reason),
                }
            )

    total = distinct + redundant
    return _scored(
        round(distinct / total, 4) if total else None,
        distinct=distinct,
        redundant=redundant,
        total=total,
        redundant_pairs=redundant_pairs,
    )


async def comparative_vs_champion(item: dict, ctx: EvalContext) -> dict | None:
    """Pairwise MT-Bench-style review of candidate vs champion (advisory only).

    Returns None if item["champion"] is not present.
    Returns {score, candidate, champion, more_consistent}; score is None (structured
    pairwise comparison, no single aggregate).
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
    out = await ctx.client.judge(SYSTEM, user, _Comparison)
    return _scored(None, candidate=out.candidate, champion=out.champion, more_consistent=out.more_consistent)


# ── flycanon custom metrics ───────────────────────────────────────────────────────


async def _rag_score_once(item: dict, ctx: EvalContext) -> _RagScore | None:
    """Single RAG scoring call returning a _RagScore (or None if item lacks Q/A)."""
    question = item.get("question", "")
    reference = item.get("reference", "")
    answer = item.get("answer", "")
    if not question or not answer:
        return None
    user = f"QUESTION: {question}\nREFERENCE: {reference}\nANSWER: {answer}\n\n{RUBRIC}"
    return await ctx.client.judge(SYSTEM_RAG, user, _RagScore)


async def contains_answer(item: dict, ctx: EvalContext) -> dict | None:
    """Flycanon: does the answer contain the correct information from the reference?

    Returns {score} in [0,1], or None if the item lacks question/answer.
    """
    result = await _rag_score_once(item, ctx)
    if result is None or result.contains_answer is None:
        return None
    return _scored(round(result.contains_answer, 4))


async def addresses_question(item: dict, ctx: EvalContext) -> dict | None:
    """Flycanon: does the answer directly address what the question is asking?

    Returns {score} in [0,1], or None if the item lacks question/answer.
    """
    result = await _rag_score_once(item, ctx)
    if result is None or result.addresses_question is None:
        return None
    return _scored(round(result.addresses_question, 4))


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
        return ChatAnthropic(model=model, api_key=api_key, temperature=0.0)  # type: ignore[call-arg,arg-type]
    if provider == "openai":
        from langchain_openai import ChatOpenAI  # type: ignore[import]  # noqa: PLC0415

        api_key = os.environ.get("OPENAI_API_KEY", "")
        return ChatOpenAI(model=model, api_key=api_key, temperature=0.0)  # type: ignore[call-arg,arg-type]
    if provider == "azure":
        from langchain_openai import AzureChatOpenAI  # type: ignore[import]  # noqa: PLC0415

        return AzureChatOpenAI(  # type: ignore[call-arg]
            azure_deployment=model,
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),  # type: ignore[arg-type]
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            temperature=0.0,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore[import]  # noqa: PLC0415

        return ChatOllama(model=model, temperature=0.0)
    raise ValueError(f"RAGAS: unsupported provider {provider!r}")


def _build_embeddings(ctx: EvalContext):
    """Wrap the framework embedder (``ctx.embedder``) for RAGAS.

    RAGAS consumes a LangChain ``Embeddings`` via ``LangchainEmbeddingsWrapper``;
    we feed it a thin adapter over the fireflyframework_agentic ``BaseEmbedder`` so
    RAGAS uses the same embedder (and provider) as the rest of the pipeline. Build
    one with :func:`fireflyframework_agentic.evaluation.build_embedder`.
    """
    from langchain_core.embeddings import Embeddings  # type: ignore[import]  # noqa: PLC0415
    from ragas.embeddings import LangchainEmbeddingsWrapper  # type: ignore[import]  # noqa: PLC0415

    embedder = ctx.embedder
    if embedder is None:
        raise ValueError(
            "RAGAS metrics need an embedder; set EvalContext.embedder=build_embedder('<provider>:<model>')"
        )

    class _FrameworkEmbeddings(Embeddings):
        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            return (await embedder.embed(texts)).embeddings

        async def aembed_query(self, text: str) -> list[float]:
            return await embedder.embed_one(text)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return asyncio.run(self.aembed_documents(texts))

        def embed_query(self, text: str) -> list[float]:
            return asyncio.run(self.aembed_query(text))

    return LangchainEmbeddingsWrapper(_FrameworkEmbeddings())


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
        embeddings = _build_embeddings(ctx)
        metric = metric_cls(llm=llm, embeddings=embeddings)
        sample = _make_ragas_sample(item)
        dataset = EvaluationDataset(samples=[sample])
        result = evaluate(dataset=dataset, metrics=[metric])
        df = result.to_pandas()  # type: ignore[attr-defined]
        col = df.columns[df.columns.str.contains(metric_name.replace("ragas_", "").replace("_ragas", ""), case=False)]
        if col.empty:
            return None
        val = df[col[0]].iloc[0]
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return round(float(val), 4)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


async def answer_correctness(item: dict, ctx: EvalContext) -> dict | None:
    """RAGAS answer correctness (semantic F1 against reference). Returns {score} or None."""
    val = await _ragas_score("answer_correctness", item, ctx)
    return _scored(val) if val is not None else None


async def ragas_faithfulness(item: dict, ctx: EvalContext) -> dict | None:
    """RAGAS faithfulness: fraction of the answer's atomic claims grounded in contexts.

    Runs the ragas library's Faithfulness metric on a RAG Q&A item. RAGAS first decomposes
    ``answer`` into atomic claims (one LLM pass), then verifies each claim against the
    retrieved ``contexts`` (a verdict per claim); the score is supported_claims /
    total_claims. Returns {score} in [0, 1], or None when it cannot be computed.

    Differs from the custom ``faithfulness``: that one judges each discovery FINDING as a
    whole against its own CITED excerpts (not retrieved contexts) and reports a
    {score, supported, total, unsupported_ids} tally over findings. This one grades a
    free-text RAG answer's grounding in its contexts.
    """
    val = await _ragas_score("ragas_faithfulness", item, ctx)
    return _scored(val) if val is not None else None


async def context_recall(item: dict, ctx: EvalContext) -> dict | None:
    """RAGAS context recall (reference coverage by retrieved contexts). Returns {score} or None."""
    val = await _ragas_score("context_recall", item, ctx)
    return _scored(val) if val is not None else None


async def context_precision(item: dict, ctx: EvalContext) -> dict | None:
    """RAGAS context precision (retrieved contexts relevant to the question). Returns {score} or None."""
    val = await _ragas_score("context_precision", item, ctx)
    return _scored(val) if val is not None else None


# ── metric families ──────────────────────────────────────────────────────────────

# Domain-agnostic LLM / RAG answer-quality metrics.
BASIC_METRICS: tuple[str, ...] = (
    "contains_answer",
    "addresses_question",
    "answer_correctness",
    "ragas_faithfulness",
    "context_recall",
    "context_precision",
)

# Flyradar process-mining discovery-report metrics.
PROCESS_MINING_METRICS: tuple[str, ...] = (
    "source_coverage",
    "excerpt_fill_rate",
    "semantic_recovery",
    "faithfulness",
    "numeric_temporal_fidelity",
    "citation_relevance",
    "nc_semantic_precision",
    "fabricated_entity",
    "contradiction",
    "open_gap",
    "actionability",
    "severity_calibration",
    "answer_relevancy",
    "surface_deduplication",
    "comparative_vs_champion",
)

_METRIC_FNS: dict[str, Metric] = {
    "source_coverage": source_coverage,
    "excerpt_fill_rate": excerpt_fill_rate,
    "semantic_recovery": semantic_recovery,
    "faithfulness": faithfulness,
    "numeric_temporal_fidelity": numeric_temporal_fidelity,
    "citation_relevance": citation_relevance,
    "nc_semantic_precision": nc_semantic_precision,
    "fabricated_entity": fabricated_entity,
    "contradiction": contradiction,
    "open_gap": open_gap,
    "actionability": actionability,
    "severity_calibration": severity_calibration,
    "answer_relevancy": answer_relevancy,
    "surface_deduplication": surface_deduplication,
    "comparative_vs_champion": comparative_vs_champion,
    "contains_answer": contains_answer,
    "addresses_question": addresses_question,
    "answer_correctness": answer_correctness,
    "ragas_faithfulness": ragas_faithfulness,
    "context_recall": context_recall,
    "context_precision": context_precision,
}


def _selected_metric_names(metrics: str) -> tuple[str, ...]:
    if metrics == "basic":
        return BASIC_METRICS
    if metrics == "process_mining":
        return PROCESS_MINING_METRICS
    if metrics == "all":
        return BASIC_METRICS + PROCESS_MINING_METRICS
    raise ValueError(f"metrics must be 'all', 'basic', or 'process_mining'; got {metrics!r}")


# ── orchestrator ─────────────────────────────────────────────────────────────────


async def run_judge(
    item: dict,
    ctx: EvalContext,
    *,
    metrics: str = "all",
    pipeline_model: str = "",
) -> AdvisoryReport:
    """Run the selected metric family concurrently and return an AdvisoryReport.

    ``metrics`` selects which family runs: ``"basic"`` (domain-agnostic LLM/RAG
    answer-quality), ``"process_mining"`` (flyradar discovery-report), or ``"all"``.
    Best-effort: never raises. Failing metrics append to report.errors.
    """
    report = AdvisoryReport(
        judge_model=ctx.client.model_spec,
        same_provider_caveat=same_provider(pipeline_model, ctx.client.model_spec),
    )
    selected = [(name, _METRIC_FNS[name]) for name in _selected_metric_names(metrics)]

    async def _run_one(name: str, fn: Metric) -> None:
        try:
            result = await fn(item, ctx)
            if result is not None:
                report.metrics[name] = result
        except Exception as exc:
            report.errors.append(f"{name}: {type(exc).__name__}: {exc}")

    await asyncio.gather(*[_run_one(name, fn) for name, fn in selected])
    return report
