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
"""Four gates — every gate always runs; a failure raises a flag, not a veto.

Gate pipeline (EVALUATION_FRAMEWORK.md §6):
    G1 — Structural & Safe
    G2 — Must-finds & negative controls
    G3 — Evidence (grounding)
    G5 — No-regression / promotion (human decision)

Each gate is a pure function of the result dict + supporting inputs.
run_gates() always executes all four gates and returns all four results so
the scorecard carries the complete picture regardless of which flags fire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fireflyframework_agentic.evaluation import matcher
from fireflyframework_agentic.evaluation.corpus import (
    EMPTY,
    FABRICATED,
    SOURCE_UNKNOWN,
    VERIFIED,
    Corpus,
    corpus_sha256,
    verify_evidence_index,
)
from fireflyframework_agentic.evaluation.matcher import anchored, matches
from fireflyframework_agentic.evaluation.registry import Registry, registry_sha256


@dataclass
class GateResult:
    gate: str
    passed: bool
    reason_code: str = ""
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "PASS" if self.passed else f"FLAG:{self.reason_code}"
        return f"[{self.gate}] {status}"


class Verdict:
    """Promotion gate verdict constants.

    Use ``Verdict.PROMOTE`` when the challenger meets the quality bar and
    is safe to become the new champion.  Use ``Verdict.HOLD`` when the
    challenger does not meet the bar and must be iterated on.
    """

    PROMOTE: str = "PROMOTE"
    HOLD: str = "HOLD"


def render_scorecard(gate_results: list[GateResult]) -> str:
    """Render a human-readable scorecard from a list of GateResult objects.

    Emits one line per gate: ``[G1] PASS`` or ``[G2] FLAG:RECALL_BELOW_FLOOR``.
    The overall verdict (PROMOTE / HOLD) appears on the final line.  A run
    promotes only when every gate passes; any flag signals HOLD.
    """
    lines = [str(r) for r in gate_results]
    all_passed = all(r.passed for r in gate_results)
    verdict = Verdict.PROMOTE if all_passed else Verdict.HOLD
    lines.append(f"VERDICT: {verdict}")
    return "\n".join(lines)


def _build_evidence_index(result: dict, corpus: Corpus | None = None) -> dict[str, dict]:
    """Index evidence by id; with a corpus, drop entries that fail verification.

    Dropped entries (FABRICATED excerpt or SOURCE_UNKNOWN locator) cannot
    contribute source stems to G2's shared-source guard or excerpts to G3's
    grounding — a run cannot anchor anything on evidence it invented.  EMPTY
    entries are kept: an empty excerpt is a format problem, not fabrication,
    and its (verified) locator stem is still a legitimate citation.
    """
    index = {ev["id"]: ev for ev in result.get("evidence_index", []) if ev.get("id")}
    if corpus is None:
        return index
    statuses = verify_evidence_index(corpus, result)
    return {
        eid: ev
        for eid, ev in index.items()
        if statuses[eid] in (VERIFIED, EMPTY)
    }


# ── G1: Structural & Safe ────────────────────────────────────────────────────


def _name_duplication_rate(nodes: list[dict]) -> float:
    """Tier-1 + Tier-2 name clustering; returns 1 - clusters/count.

    Tier 1: same normalized id (lower-case) merges nodes into one cluster.
    Tier 2: name token-Jaccard >= 0.6 merges nodes into one cluster.

    Report-only: no gate flag fires on any threshold.
    """
    n = len(nodes)
    if n < 2:
        return 0.0

    group = list(range(n))

    def _root(i: int) -> int:
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    seen: dict[str, int] = {}
    for i, node in enumerate(nodes):
        nid = node.get("id", "").lower()
        if nid in seen:
            group[_root(i)] = _root(seen[nid])
        else:
            seen[nid] = i

    toks = [frozenset(node.get("name", "").lower().split()) for node in nodes]
    for i in range(n):
        for j in range(i + 1, n):
            a, b = toks[i], toks[j]
            union_ab = a | b
            if union_ab and len(a & b) / len(union_ab) >= 0.6:
                group[_root(i)] = _root(j)

    clusters = len({_root(i) for i in range(n)})
    return round(1 - clusters / n, 4)


def g1_structural(
    result: dict,
    registry: Registry,
    registry_path: str,
    *,
    pii_list: list[str] | None = None,
    corpus: Corpus | None = None,
) -> GateResult:
    """G1 — Structural & Safe (hard veto).

    Checks (in order):
    1. EMPTY_MUST_FIND — must run first; kills the fake-100%-champion bug.
    2. Registry SHA-256 pin: loaded Registry matches the file on disk.
    3. Corpus SHA-256 pin (when a corpus is supplied): same drift guard for
       the evidence universe (CORPUS_DRIFT).
    4. Required top-level keys present in result.
    5. PII non-disclosure: no corpus PII name in any finding/report text.
    """
    # Guard 1: empty registry (fake-champion guard — always first)
    if not registry.real_items:
        return GateResult(
            gate="G1",
            passed=False,
            reason_code="EMPTY_MUST_FIND",
            details={"message": "Registry has zero real items — cannot evaluate recall."},
        )

    # Guard 2: registry SHA-256 pin
    computed_sha = registry_sha256(registry_path)
    if computed_sha != registry.sha256():
        return GateResult(
            gate="G1",
            passed=False,
            reason_code="GOLD_DRIFT",
            details={
                "message": "Registry file has changed since it was loaded.",
                "expected": registry.sha256(),
                "actual": computed_sha,
            },
        )

    # Guard 3: corpus SHA-256 pin (CORPUS_DRIFT — the GOLD_DRIFT twin for evidence)
    if corpus is not None:
        current_corpus_sha = corpus_sha256(corpus.path)
        if current_corpus_sha != corpus.sha256:
            return GateResult(
                gate="G1",
                passed=False,
                reason_code="CORPUS_DRIFT",
                details={
                    "message": "Corpus file has changed since it was loaded.",
                    "expected": corpus.sha256,
                    "actual": current_corpus_sha,
                },
            )

    # Guard 4: required result keys
    required = ("process_graph", "findings", "evidence_index")
    missing = [k for k in required if k not in result]
    if missing:
        return GateResult(
            gate="G1",
            passed=False,
            reason_code="SCHEMA_INVALID",
            details={"missing_keys": missing},
        )

    # Guard 5: PII check
    if pii_list:
        free_text: list[str] = []
        for finding in result.get("findings", []):
            free_text.extend([finding.get("title", ""), finding.get("description", "")])
        for report in result.get("reports", []):
            free_text.append(str(report))
        combined = " ".join(free_text).lower()
        hits = [name for name in pii_list if name.lower() in combined]
        if hits:
            return GateResult(
                gate="G1",
                passed=False,
                reason_code="PII_LEAK",
                details={
                    "message": "Corpus PII names found in findings/reports.",
                    "matches": hits[:5],
                },
            )

    pg = result.get("process_graph", {})
    processes = pg.get("processes", [])
    activities = [a for p in processes for a in p.get("activities", [])]
    decisions = [d for p in processes for d in p.get("decisions", [])]
    dg = result.get("dependency_graph", {})

    details = {
        "registry_sha256": registry.sha256(),
        "real_items": len(registry.real_items),
        "nc_items": len(registry.nc_items),
        "map": {
            "processes": {
                "count": len(processes),
                "duplication_rate": _name_duplication_rate(processes),
            },
            "activities": {
                "count": len(activities),
                "duplication_rate": _name_duplication_rate(activities),
            },
            "decisions": {
                "count": len(decisions),
                "duplication_rate": _name_duplication_rate(decisions),
            },
            "personas": {
                "count": len(result.get("personas", [])),
                "duplication_rate": _name_duplication_rate(result.get("personas", [])),
            },
            "systems": {
                "count": len(result.get("systems", [])),
                "duplication_rate": _name_duplication_rate(result.get("systems", [])),
            },
            "informal_channels": {
                "count": len(result.get("informal_channels", [])),
                "duplication_rate": _name_duplication_rate(result.get("informal_channels", [])),
            },
            "dependency_graph_edges": len(dg.get("activity_edges", [])),
        },
    }
    if corpus is not None:
        details["corpus_sha256"] = corpus.sha256
    return GateResult(gate="G1", passed=True, details=details)


# ── G2: Recall & Precision ───────────────────────────────────────────────────


def _candidates_by_scope(result: dict) -> dict[str, list[dict]]:
    """Build per-scope candidate lists from a DiscoveryResult (§4.3).

    Process candidates are augmented with their children's evidence_refs because
    process nodes typically carry no own refs — the source-document guard uses the
    union of the process's own refs and all its activities' and decisions' refs.

    dependency_graph-scoped items are relation items (all carry from/to) and are
    matched via matcher.matches_dependency_graph_relation() — not through per-candidate
    iteration — so no "dependency_graph" key is included here.
    """
    pg = result.get("process_graph", {})
    processes = pg.get("processes", [])

    def _merge_refs(proc: dict) -> dict:
        children_refs = [
            ref
            for child_list in (proc.get("activities", []), proc.get("decisions", []))
            for child in child_list
            for ref in child.get("evidence_refs", [])
        ]
        return {**proc, "evidence_refs": list(proc.get("evidence_refs", [])) + children_refs}

    return {
        "process": [_merge_refs(p) for p in processes],
        "activity": [a for p in processes for a in p.get("activities", [])],
        "decision": [d for p in processes for d in p.get("decisions", [])],
        "finding": result.get("findings", []),
        "action": result.get("proposed_actions", []),
        "persona": result.get("personas", []),
        "system": result.get("systems", []),
        "informal_channel": result.get("informal_channels", []),
    }


def _weighted_recall(scored_items: list, hits: dict[str, bool]) -> float:
    """Weighted recall of a hit map over the scored (non-L3) items."""
    total_weight = sum(item.weight for item in scored_items) or 1.0
    weighted_hit = sum(item.weight for item in scored_items if hits[item.id])
    return weighted_hit / total_weight


def _finding_redundancy_rate(findings: list[dict]) -> float:
    """Fraction of findings that are near-duplicates of another (Jaccard ≥0.6 on ≥5-char tokens)."""
    if len(findings) < 2:
        return 0.0
    def _tok(text: str) -> frozenset[str]:
        return frozenset(t.lower() for t in text.split() if len(t) >= 5)
    token_sets = [_tok(f.get("description", "")) for f in findings]
    in_redundant: set[int] = set()
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a, b = token_sets[i], token_sets[j]
            union = a | b
            sim = len(a & b) / len(union) if union else 1.0
            if sim >= 0.6:
                in_redundant.add(i)
                in_redundant.add(j)
    return round(len(in_redundant) / len(findings), 4)


def g2_recall_precision(
    result: dict,
    registry: Registry,
    *,
    recall_floor: float = 0.70,
    embed_fn=None,
    tau: float = 0.70,
    tau_nc: float = 0.85,
    recall_metric: str = "lexical",
    corpus: Corpus | None = None,
) -> GateResult:
    """G2 — Recall & Precision (hard veto).

    - L0 miss  -> BLOCK (zeros the evaluation; regulatory-mandatory item absent)
    - NC hit   -> BLOCK (precision failure; plausible-but-false item was emitted)
    - recall < floor -> BLOCK

    With a ``corpus``, evidence entries that fail verification (fabricated
    excerpt or unknown source) are excluded from the evidence index before
    matching, so the shared-source guard only accepts citations to real
    corpus documents — a fabricated locator cannot satisfy any item.

    ``recall_metric`` ("lexical"/"semantic"/"hybrid") selects which hit map GATES.
    "lexical" is matcher.matches (shared-source + topic-anchored token overlap) and
    needs no embedder.  "semantic"/"hybrid" add the embedding path (matcher.semantic_hits,
    threshold ``tau`` for real items, ``tau_nc`` for NC items) and REQUIRE ``embed_fn``
    — passing them without one raises ValueError (use "lexical" for the offline path).
    When an embedder is supplied, all three recalls (lexical/semantic/hybrid) are
    reported in details regardless of which one gates.
    """
    evidence_index = _build_evidence_index(result, corpus)
    candidates = _candidates_by_scope(result)
    findings = candidates["finding"]

    # NC items anchor via the embedding path only (§6.2): a correct finding about
    # the true mirror fact shares vocabulary with the false description, so a
    # token or keyword match would falsely convict it.  Lexical NC is always False.
    # dependency_graph relation items (those with from_node) use the endpoint
    # matcher (§5.3b) instead of the per-candidate text predicate.
    lexical: dict[str, bool] = {}
    for item in registry.items:
        if item.tier == "NC":
            lexical[item.id] = False
        elif item.scope == "dependency_graph" and item.from_node:
            lexical[item.id] = matcher.matches_dependency_graph_relation(
                item, result, evidence_index
            )
        else:
            lexical[item.id] = any(
                matches(c, item, evidence_index, scope=scope)
                for scope in matcher.allowed_scopes(item)
                for c in candidates.get(scope, [])
            )

    if recall_metric not in ("lexical", "semantic", "hybrid"):
        raise ValueError(f"unknown recall_metric {recall_metric!r}")
    if recall_metric in ("semantic", "hybrid") and embed_fn is None:
        raise ValueError(
            f"recall_metric={recall_metric!r} requires an embedder; pass embed_fn"
        )

    if embed_fn is not None:
        semantic = matcher.semantic_hits(
            candidates, registry.items, evidence_index, embed_fn, tau, tau_nc=tau_nc
        )
        # dependency_graph relation items have no embedding candidates (§5.3b uses
        # the endpoint matcher, not per-candidate text embeddings); mirror the
        # lexical result so semantic/hybrid never under-credits them.
        for item in registry.items:
            if item.scope == "dependency_graph" and item.from_node:
                semantic[item.id] = lexical[item.id]
    else:
        semantic = None

    metric = recall_metric

    if semantic is None or metric == "lexical":
        hits = lexical
    elif metric == "semantic":
        hits = semantic
    else:  # hybrid
        hits = {iid: lexical[iid] or semantic[iid] for iid in lexical}

    # Signal-to-noise panel — report-only, §6.2 item 3
    finding_count = len(findings)
    finding_scoped_items = [i for i in registry.real_items if i.scope == "finding"]
    findings_matched = sum(
        1 for f in findings
        if any(matches(f, item, evidence_index, scope="finding") for item in finding_scoped_items)
    )
    _sn = {
        "finding_count": finding_count,
        "findings_matched_to_registry": {
            "count": findings_matched,
            "fraction": round(findings_matched / finding_count, 4) if finding_count else 0.0,
        },
        "finding_redundancy_rate": _finding_redundancy_rate(findings),
    }
    if corpus is not None:
        excluded = len(_build_evidence_index(result)) - len(evidence_index)
        _sn["evidence_entries_excluded_unverified"] = excluded

    # L0 misses
    l0_misses = [item.id for item in registry.l0_items if not hits[item.id]]
    if l0_misses:
        return GateResult(
            gate="G2",
            passed=False,
            reason_code="L0_MISSING",
            details={
                "l0_misses": l0_misses,
                "message": "Regulatory-mandatory items not found — evaluation zeroed.",
                **_sn,
            },
        )

    # NC precision
    nc_hits = [item.id for item in registry.nc_items if hits[item.id]]
    if nc_hits:
        return GateResult(
            gate="G2",
            passed=False,
            reason_code="NC_HIT",
            details={
                "nc_hits": nc_hits,
                "message": "Plausible-but-false negative control items were matched — precision failure.",
                **_sn,
            },
        )

    # Weighted recall — over scored items only (L0/L1/L2).  L3 is a bonus tier
    # ("extra credit"): an L3 miss must not lower recall, so L3 is excluded from
    # the denominator and only reported in per_tier below.  Recall is computed over
    # the GATING hit map so the gate is internally consistent with the chosen metric.
    real_items = registry.real_items
    scored_items = [item for item in real_items if item.tier != "L3"]
    recall = _weighted_recall(scored_items, hits)

    per_tier: dict[str, dict] = {}
    for tier in ("L0", "L1", "L2", "L3"):
        tier_items = [i for i in real_items if i.tier == tier]
        if not tier_items:
            continue
        per_tier[tier] = {
            "hit": sum(1 for i in tier_items if hits[i.id]),
            "total": len(tier_items),
        }

    def _semantic_details() -> dict:
        """The extra recall-breakdown keys, only emitted when an embedder is given."""
        if semantic is None:
            return {}
        return {
            "lexical_recall": round(_weighted_recall(scored_items, lexical), 4),
            "semantic_recall": round(_weighted_recall(scored_items, semantic), 4),
            "hybrid_recall": round(
                _weighted_recall(
                    scored_items, {iid: lexical[iid] or semantic[iid] for iid in lexical}
                ),
                4,
            ),
            "tau": tau,
        }

    if recall < recall_floor:
        return GateResult(
            gate="G2",
            passed=False,
            reason_code="RECALL_BELOW_FLOOR",
            details={
                "recall": round(recall, 4),
                "recall_metric": metric,
                "floor": recall_floor,
                "per_tier": per_tier,
                "misses": [item.id for item in scored_items if not hits[item.id]],
                **_semantic_details(),
                **_sn,
            },
        )

    return GateResult(
        gate="G2",
        passed=True,
        details={
            "recall": round(recall, 4),
            "recall_metric": metric,
            "floor": recall_floor,
            "per_tier": per_tier,
            "nc_items_checked": len(registry.nc_items),
            **_semantic_details(),
            **_sn,
        },
    )


# ── G3: Grounded ─────────────────────────────────────────────────────────────


def g3_grounded(
    result: dict,
    *,
    grounding_floor: float = 0.90,
    human_spot_check_n: int = 5,
    corpus: Corpus | None = None,
) -> GateResult:
    """G3 — Grounded (automated portion; human spot-check triggered on pass).

    For each finding, verifies that at least one cited evidence excerpt shares a
    non-trivial token with the finding description (topic-anchoring).

    With a ``corpus``, the gate also looks in a third direction — cited ->
    exists: every evidence entry is verified against the actual corpus text
    (corpus.verify_entry).  A populated excerpt not found in its cited source
    raises EVIDENCE_FABRICATED; a locator resolving to no corpus document
    raises EVIDENCE_SOURCE_UNKNOWN; and only verified excerpts can ground a
    finding, so a run cannot ground itself on evidence it invented.

    Also reports excerpt fill rate and source coverage so the reviewer can tell
    whether ungrounded findings are a format problem (empty excerpts) or a real
    faithfulness signal (populated excerpts that do not anchor).

    Known limitation: topic-anchoring, not claim entailment.  A '45 days' claim
    cited to a '3 days' source passes if they share the process name (excerpt
    verification confirms the quote is real, not that the claim matches it).
    The human spot-check is the binding faithfulness signal until NLI/AIS lands.
    """
    evidence_index = _build_evidence_index(result)
    findings = result.get("findings", [])
    statuses = verify_evidence_index(corpus, result) if corpus is not None else None

    if not findings:
        return GateResult(
            gate="G3",
            passed=False,
            reason_code="NO_FINDINGS",
            details={"message": "Result has zero findings — cannot compute grounding."},
        )

    grounded_ids: list[str] = []
    # Ungrounded split (§6.3): distinguish format issues from real faithfulness failures.
    ungrounded_empty_only: list[str] = []    # every ref had an empty excerpt
    ungrounded_populated: list[str] = []     # had populated excerpt(s) but none anchored

    # Excerpt fill: count all resolved refs and how many carry a non-empty excerpt.
    total_refs = 0
    populated_refs = 0

    # Source coverage: which source stems are cited by at least one finding.
    cited_stems: set[str] = set()

    for finding in findings:
        fid = finding.get("id", "?")
        desc = finding.get("description", "")
        is_grounded = False
        had_populated = False
        for ref in finding.get("evidence_refs", []):
            ev = evidence_index.get(ref.get("evidence_id", ""))
            if ev:
                total_refs += 1
                excerpt = ev.get("excerpt") or ""
                if excerpt:
                    populated_refs += 1
                    had_populated = True
                    # Track source coverage (even for ungrounded findings).
                    stem = matcher.source_stem(ev.get("locator", ""))
                    if stem:
                        cited_stems.add(stem)
                    # Only a corpus-verified excerpt can ground a finding.
                    if statuses is not None and statuses.get(ev.get("id")) != VERIFIED:
                        continue
                    if anchored(desc, excerpt):
                        is_grounded = True
                        break
        if is_grounded:
            grounded_ids.append(fid)
        elif had_populated:
            ungrounded_populated.append(fid)
        else:
            ungrounded_empty_only.append(fid)

    grounding_pct = len(grounded_ids) / len(findings)

    # All source stems present in the evidence index (not just those cited).
    all_stems: set[str] = set()
    for ev in result.get("evidence_index", []):
        stem = matcher.source_stem(ev.get("locator", ""))
        if stem:
            all_stems.add(stem)
    orphaned = sorted(all_stems - cited_stems)

    excerpt_fill = f"{populated_refs}/{total_refs}" if total_refs else "0/0"
    source_coverage = f"{len(cited_stems)}/{len(all_stems)}" if all_stems else "0/0"

    details = {
        "grounding_pct": round(grounding_pct, 4),
        "grounded": len(grounded_ids),
        "total": len(findings),
        "excerpt_fill": excerpt_fill,
        "source_coverage": source_coverage,
        "orphaned_sources": orphaned,
    }

    fabricated_ids: list[str] = []
    unknown_source_ids: list[str] = []
    if statuses is not None:
        fabricated_ids = sorted(e for e, s in statuses.items() if s == FABRICATED)
        unknown_source_ids = sorted(e for e, s in statuses.items() if s == SOURCE_UNKNOWN)
        details["evidence_verification"] = {
            "entries": len(statuses),
            "verified": sum(1 for s in statuses.values() if s == VERIFIED),
            "empty_excerpt": sum(1 for s in statuses.values() if s == EMPTY),
            "fabricated": fabricated_ids,
            "source_unknown": unknown_source_ids,
        }

    if fabricated_ids:
        details["message"] = (
            "Populated excerpt(s) not found in the cited corpus document — "
            "the run asserts evidence the source does not contain."
        )
        return GateResult(
            gate="G3", passed=False, reason_code="EVIDENCE_FABRICATED", details=details
        )

    if unknown_source_ids:
        details["message"] = (
            "Evidence locator(s) resolve to no corpus document — either the "
            "corpus bundle is incomplete or the run invented a source."
        )
        return GateResult(
            gate="G3", passed=False, reason_code="EVIDENCE_SOURCE_UNKNOWN", details=details
        )

    if grounding_pct < grounding_floor:
        details["floor"] = grounding_floor
        details["ungrounded_with_populated_excerpts"] = ungrounded_populated
        details["ungrounded_with_empty_excerpts_only"] = ungrounded_empty_only
        return GateResult(gate="G3", passed=False, reason_code="UNGROUNDED", details=details)

    spot_n = min(human_spot_check_n, len(findings))
    details["human_spot_check"] = (
        f"ACTION REQUIRED: manually review {spot_n} sampled findings for "
        "field-consistency, citation-accuracy, and client-readiness.  "
        "This is the binding faithfulness signal until NLI/AIS lands."
    )
    return GateResult(gate="G3", passed=True, details=details)


# ── G5: No-regression / promotion (human decision) ───────────────────────────


def g5_no_regression(
    candidate_scores: dict[str, float],
    champion_scores: dict[str, float] | None,
    aa_noise: dict[str, float] | None,
    *,
    is_day_zero: bool = False,
    human_signed_off: bool = False,
    signoff_count: int = 0,
) -> GateResult:
    """G5 — No-regression / promotion gate (human decision).

    Day-Zero: no champion exists.  Requires G1-G3 pass + 2 independent sign-offs.
    Normal promotion: candidate must beat champion by > aa_noise on every metric,
    no guardrail regresses, + 1 human sign-off.

    Champions are per-corpus.  Do not compare across corpora.
    """
    if is_day_zero or champion_scores is None:
        required = 2
        if signoff_count < required:
            return GateResult(
                gate="G5",
                passed=False,
                reason_code="HOLD",
                details={
                    "reason": (
                        f"Day-Zero requires {required} independent human sign-offs "
                        f"(kappa >= 0.70); got {signoff_count}."
                    ),
                    "action": "Collect sign-offs, then re-run with --day-zero --signoffs 2",
                },
            )
        return GateResult(
            gate="G5",
            passed=True,
            details={"day_zero": True, "signoffs": signoff_count},
        )

    if not human_signed_off:
        return GateResult(
            gate="G5",
            passed=False,
            reason_code="HOLD",
            details={"reason": "Human sign-off required for promotion."},
        )

    noise = aa_noise or {}
    regressions: list[str] = []
    improvements: list[str] = []

    for metric, cand_val in candidate_scores.items():
        champ_val = champion_scores.get(metric)
        if champ_val is None:
            continue
        delta = cand_val - champ_val
        band = noise.get(metric, 0.0)
        if delta < -band:
            regressions.append(
                f"{metric}: candidate={cand_val:.4f} champion={champ_val:.4f} "
                f"delta={delta:+.4f} < -band={-band:.4f}"
            )
        elif delta > band:
            improvements.append(f"{metric}: delta={delta:+.4f} > band={band:.4f}")

    if regressions:
        return GateResult(
            gate="G5",
            passed=False,
            reason_code="HOLD",
            details={
                "regressions": regressions,
                "improvements": improvements,
                "message": "Guardrail metric(s) regressed beyond A/A noise band.",
            },
        )

    return GateResult(
        gate="G5",
        passed=True,
        details={"improvements": improvements, "noise_band": noise},
    )


# ── Full gate pipeline ────────────────────────────────────────────────────────


def run_gates(
    result: dict,
    registry: Registry,
    registry_path: str,
    *,
    pii_list: list[str] | None = None,
    recall_floor: float = 0.70,
    grounding_floor: float = 0.90,
    champion_scores: dict[str, float] | None = None,
    aa_noise: dict[str, float] | None = None,
    is_day_zero: bool = False,
    human_signed_off: bool = False,
    signoff_count: int = 0,
    embed_fn=None,
    tau: float = 0.70,
    tau_nc: float = 0.85,
    recall_metric: str = "lexical",
    corpus: Corpus | None = None,
) -> list[GateResult]:
    """Run all gates G1 -> G2 -> G3 -> G5; every gate always executes.

    A failed gate raises a flag in its GateResult but never prevents the
    remaining gates from running.  The scorecard therefore always carries the
    complete picture: a run that misses a regulatory item *and* grounds poorly
    shows both flags.  See EVALUATION_FRAMEWORK.md §2 ('No gate vetoes').

    ``corpus`` (optional) enables deterministic evidence verification: G1 pins
    the corpus hash, G2 ignores unverified evidence entries, and G3 flags
    fabricated excerpts and unknown sources.  Without it, evidence is taken at
    face value from the run's own evidence_index (disclosed on the scorecard).

    Returns all four GateResult objects.
    """
    g1 = g1_structural(result, registry, registry_path, pii_list=pii_list, corpus=corpus)

    g2 = g2_recall_precision(
        result,
        registry,
        recall_floor=recall_floor,
        embed_fn=embed_fn,
        tau=tau,
        tau_nc=tau_nc,
        recall_metric=recall_metric,
        corpus=corpus,
    )

    g3 = g3_grounded(result, grounding_floor=grounding_floor, corpus=corpus)

    # G5 uses whatever scores G2/G3 produced; 0.0 when a gate flagged and did
    # not emit the metric (e.g. L0_MISSING returns before computing recall).
    candidate_scores = {
        "recall": g2.details.get("recall", 0.0),
        "grounding_pct": g3.details.get("grounding_pct", 0.0),
    }
    g5 = g5_no_regression(
        candidate_scores,
        champion_scores,
        aa_noise,
        is_day_zero=is_day_zero,
        human_signed_off=human_signed_off,
        signoff_count=signoff_count,
    )

    return [g1, g2, g3, g5]
