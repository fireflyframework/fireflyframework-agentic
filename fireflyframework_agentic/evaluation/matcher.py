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

"""Single matching primitive reused across G2 (recall/precision) and G3 (grounding).

anchored() is topic-level lexical overlap.  matches() is the gate predicate.
One function, three uses — do not write three matching functions.

Known limitation (EVALUATION_FRAMEWORK.md): anchored() is topic-anchored, not claim-verified.
A '45 days' claim cited to a '3 days' source passes if they share the process name.
Real claim entailment (NLI/AIS) is Phase 2.  The G3 human spot-check is the
binding faithfulness signal until then.
"""

from __future__ import annotations

import re

import numpy as np

from fireflyframework_agentic.evaluation.judge_client import cosine


def tokens(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


def anchored(claim: str, evidence: str, *, min_token: int = 5) -> bool:
    """True if claim and evidence share at least one non-trivial token (>= min_token chars).

    Rejects a citation to an unrelated document.  Does NOT verify the claim value —
    that gap is closed by the deferred NLI/AIS check in Phase 2.
    """
    a = {t for t in tokens(claim) if len(t) >= min_token}
    b = {t for t in tokens(evidence) if len(t) >= min_token}
    return bool(a & b)


def source_stem(locator: str) -> str:
    """Normalize a locator/source path to a stable document stem for matching.

    Robust to the two locator conventions observed across runs:
    - directory-prefixed ('sops/SOP-002-kyc-edd.md') and bare ('SOP-002-kyc-edd.md')
      both reduce to 'sop-002-kyc-edd';
    - event-log row ids ('src-credit-underwriting:CU-2026-1003') reduce to the
      process stem 'credit-underwriting', so they join the CSV the registry cites.

    Preserves the same-document anti-gaming property of matches(): it still keys
    on which source document a finding cites — just independent of directory
    prefix, file extension, and case, so one registry scores every run.
    """
    s = locator.split("#")[0]  # drop the locator fragment (#page=N, #anchor)
    s = s.rsplit("/", 1)[-1]  # basename — strip any directory prefix
    if s.startswith("src-") and ":" in s:  # event-log row id: src-<process>:<case>
        return s.split(":", 1)[0][len("src-") :].lower()
    if "." in s:  # strip a trailing file extension
        s = s.rsplit(".", 1)[0]
    return s.lower()


def _finding_sources(finding: dict, evidence_index: dict[str, dict]) -> set[str]:
    """Return the set of normalized source-document stems cited by a finding."""
    sources: set[str] = set()
    for ref in finding.get("evidence_refs", []):
        ev = evidence_index.get(ref.get("evidence_id", ""))
        if ev:
            stem = source_stem(ev.get("locator", ""))
            if stem:
                sources.add(stem)
    return sources


def shares_source(finding: dict, item, evidence_index: dict[str, dict]) -> bool:
    """True iff the finding cites at least one source document the item lists as evidence.

    Source documents are compared by normalized stem (source_stem) so one registry
    scores every run regardless of locator convention.  This is the anti-gaming
    anchor reused by both the lexical predicate (matches) and the semantic path
    (semantic_hits): a finding on a different document cannot satisfy this item.

    Spec-style NC items list their mirror source (§4.1); legacy NC items carry
    evidence=[], which makes this always False for them.

    Args:
        finding: dict from DiscoveryResult.findings[i] (model_dump output).
        item: RegistryItem dataclass from registry.py.
        evidence_index: {evidence_id: Evidence dict} built from result['evidence_index'].
    """
    finding_sources = _finding_sources(finding, evidence_index)
    item_sources = {source_stem(e) for e in item.evidence}
    return bool(finding_sources & item_sources)


def _keyword_anchored(desc: str, keywords: list[str]) -> bool:
    """True iff any keyword appears as a whole word in desc (case-insensitive).

    Keyword rail: exempt from the 5-char token floor so short banking terms
    (KYC, PEP, AML) can anchor a match even though they are too short for the
    token rail.  Whole-word matching prevents false substring hits (e.g. "risk"
    inside "enterprise-risk-management").
    """
    if not keywords:
        return False
    desc_lower = desc.lower()
    return any(re.search(r"\b" + re.escape(kw.lower()) + r"\b", desc_lower) for kw in keywords)


def candidate_text(candidate: dict, scope: str) -> str:
    """Extract the searchable text from a candidate on the given scope surface (§4.3).

    Each scope surface uses different fields as the match text:
    - finding / action      : title + description
    - process / decision    : name + description
    - activity              : name + notes + regulatory_links
    - persona               : name + role + goals + pain_points
    - system                : name + description
    - informal_channel      : name + usage_context + notes
    - dependency_graph      : name + description (diagnostic nodes; relation items bypass this)
    """
    if scope in ("finding", "action"):
        return " ".join(filter(None, [candidate.get("title", ""), candidate.get("description", "")]))
    if scope == "activity":
        rl = candidate.get("regulatory_links") or []
        rl_str = " ".join(rl) if isinstance(rl, list) else str(rl or "")
        return " ".join(filter(None, [candidate.get("name", ""), candidate.get("notes", ""), rl_str]))
    if scope == "persona":
        goals = candidate.get("goals") or []
        pain = candidate.get("pain_points") or []
        goals_str = " ".join(goals) if isinstance(goals, list) else str(goals)
        pain_str = " ".join(pain) if isinstance(pain, list) else str(pain)
        return " ".join(
            filter(
                None,
                [
                    candidate.get("name", ""),
                    candidate.get("role", ""),
                    goals_str,
                    pain_str,
                ],
            )
        )
    if scope == "informal_channel":
        return " ".join(
            filter(
                None,
                [
                    candidate.get("name", ""),
                    candidate.get("usage_context", ""),
                    candidate.get("notes", ""),
                ],
            )
        )
    # process, decision, system, dependency_graph (diagnostic nodes)
    return " ".join(filter(None, [candidate.get("name", ""), candidate.get("description", "")]))


INSIGHT_ITEM_SCOPES = ("finding", "action")
INSIGHT_MATCH_SURFACES = ("finding", "action", "activity", "decision")


def allowed_scopes(item) -> tuple[str, ...]:
    """Candidate surfaces that may satisfy a registry item.

    Insight items (finding / action) may be satisfied by any insight or process-graph
    *leaf* surface (activity / decision): a run often grounds the same operational fact
    on a different surface than the registry's scope tag anticipates (the BBVA case —
    pain points the registry tags 'finding' that the run emitted as decision/activity
    nodes).  shares_source is still REQUIRED on every candidate (see matches /
    semantic_hits), so a candidate on the wrong document never counts — cross-scope
    widens WHERE we look, never the source anchor.

    Structural items (process / activity / decision) stay on their own surface: a
    structural must-find requires the run to have actually built that node, not merely
    mentioned the fact in a finding (test_process_scope_miss_when_no_matching_process).
    NC items are likewise scope-strict — widening a negative control's pool could only
    make it easier to trip (a specificity regression), never recover a legitimate hit.

    `process` is never a match surface for an insight item: _candidates_by_scope folds
    every child's evidence_refs into the process node, so its citation set is a union of
    many documents and shares_source goes vacuous (hence its exclusion from
    INSIGHT_MATCH_SURFACES).
    """
    if item.tier == "NC":
        return (item.scope,)
    if item.scope in INSIGHT_ITEM_SCOPES:
        return INSIGHT_MATCH_SURFACES
    return (item.scope,)


def matches(
    candidate: dict,
    item,
    evidence_index: dict[str, dict],
    scope: str = "finding",
) -> bool:
    """True iff candidate cites a shared source document AND is topic-anchored to item.

    Two-rail anchor (either rail suffices):
    - Token rail: ≥1 shared token of ≥5 chars between candidate text and item description.
    - Keyword rail: ≥1 item keyword appears as a whole word in the candidate text.
      Exempt from the 5-char floor so short banking terms (KYC, PEP, AML) can anchor.

    The ``scope`` controls which fields are read as the candidate's match text (§4.3):
    findings and actions use ``title + description``; processes and decisions use
    ``name + description``; activities use ``name + notes + regulatory_links``.

    Anti-gaming guard: a candidate on a different document cannot satisfy this item
    even if its text happens to match.  Source documents are compared by
    normalized stem (source_stem) so one registry scores every run regardless of
    locator convention.

    Args:
        candidate: dict from the DiscoveryResult surface matching ``scope``.
        item: RegistryItem dataclass from registry.py.
        evidence_index: {evidence_id: Evidence dict} built from result['evidence_index'].
        scope: surface the candidate was drawn from (default "finding").
    """
    if not shares_source(candidate, item, evidence_index):
        return False
    desc = candidate_text(candidate, scope)
    return _keyword_anchored(desc, list(item.keywords or [])) or anchored(desc, item.description)


def matches_dependency_graph_relation(
    item,
    result: dict,
    evidence_index: dict[str, dict],
) -> bool:
    """Endpoint matcher for dependency_graph relation items (§5.3b).

    Stage 1: Anchor both endpoints to activity nodes via token rail.
    Stage 2: Verify a directed edge or path connects them in the asserted direction,
             behind the shared-source guard on the edge's/path's evidence_refs.

    Returns False when either endpoint anchors to no activity, or when no connecting
    edge/path shares a source document with the item.
    """
    if not item.from_node or not item.to_node:
        return False

    processes = result.get("process_graph", {}).get("processes", [])
    all_activities = [a for p in processes for a in p.get("activities", [])]

    def _anchor(endpoint_text: str) -> set[str]:
        return {
            a["id"] for a in all_activities if a.get("id") and anchored(candidate_text(a, "activity"), endpoint_text)
        }

    from_ids = _anchor(item.from_node)
    to_ids = _anchor(item.to_node)
    if not from_ids or not to_ids:
        return False

    item_stems = {source_stem(e) for e in item.evidence}

    def _node_stems(node: dict) -> set[str]:
        return {
            source_stem(evidence_index[r["evidence_id"]].get("locator", ""))
            for r in node.get("evidence_refs", [])
            if r.get("evidence_id") in evidence_index
        }

    dg = result.get("dependency_graph", {})

    for edge in dg.get("activity_edges", []):
        if edge.get("from_node") in from_ids and edge.get("to_node") in to_ids and _node_stems(edge) & item_stems:
            return True

    for path in dg.get("critical_paths", []):
        if not (_node_stems(path) & item_stems):
            continue
        node_ids = path.get("node_ids", [])
        from_pos = [i for i, nid in enumerate(node_ids) if nid in from_ids]
        to_pos = [i for i, nid in enumerate(node_ids) if nid in to_ids]
        if any(fp < tp for fp in from_pos for tp in to_pos):
            return True

    return False


def semantic_hits(
    candidates: dict[str, list[dict]],
    items,
    evidence_index: dict[str, dict],
    embed_fn,
    tau: float = 0.70,
    tau_nc: float = 0.85,
) -> dict[str, bool]:
    """Opt-in embedding-semantic recall: {item.id: found-by-some-shared-source candidate}.

    Scope-aware: each registry item is evaluated against candidates from its own
    scope surface (finding, process, activity, decision, action) using the same
    per-scope field extraction as the lexical path (candidate_text).  Passing only
    the findings list (the previous behaviour) would leave process/activity/decision/
    action items with an empty candidate pool and a guaranteed False result.

    Real items (L0–L3): hit iff some scope-matching candidate shares a source
    document with the item (shares_source) AND is embedding-similar (cosine >= tau).
    Source anchor is preserved — a candidate on a different document cannot recover
    a real item.

    NC items (tier=="NC"): hit iff some scope-matching candidate is embedding-similar
    (cosine >= tau_nc).  When the NC lists its mirror source (§4.1) the shared-source
    guard applies; legacy NC items with evidence=[] skip the anchor, with the higher
    threshold (default 0.85) compensating.

    Cost is two embed_fn calls — all scope-appropriate candidate texts once and all
    item texts once — not O(n*m) per-pair embeddings.

    Args:
        candidates: {scope: [candidate dicts]} from _candidates_by_scope().
        items: iterable of RegistryItem dataclasses.
        evidence_index: {evidence_id: Evidence dict}.
        embed_fn: callable(list[str]) -> array-like of row vectors.
        tau: cosine threshold for real items (inclusive).
        tau_nc: cosine threshold for NC items (inclusive; higher to compensate for no source anchor).
    """
    items = list(items)

    # Flatten all candidates across scopes, preserving their scope tag for
    # text extraction and per-item filtering.
    scoped: list[tuple[str, dict]] = [(scope, cand) for scope, cands in candidates.items() for cand in cands]

    if not scoped:
        return {item.id: False for item in items}

    cand_texts = [candidate_text(cand, scope) for scope, cand in scoped]
    item_texts = [" ".join([item.description or ""] + list(item.keywords or [])).strip() for item in items]

    cand_vecs = np.asarray(embed_fn(cand_texts))
    item_vecs = np.asarray(embed_fn(item_texts))

    hits: dict[str, bool] = {}
    for i, item in enumerate(items):
        item_vec = item_vecs[i]
        allowed = allowed_scopes(item)
        hit = False
        for k, (scope, cand) in enumerate(scoped):
            if scope not in allowed:
                continue
            if item.tier == "NC":
                # Shared-source guard applies when the NC lists its mirror source
                # (§4.2/§6.2); legacy evidence=[] NCs stay unanchored, with the
                # higher tau_nc compensating.
                if item.evidence and not shares_source(cand, item, evidence_index):
                    continue
                if cosine(cand_vecs[k], item_vec) >= tau_nc:
                    hit = True
                    break
            elif shares_source(cand, item, evidence_index) and cosine(cand_vecs[k], item_vec) >= tau:
                hit = True
                break
        hits[item.id] = hit
    return hits
