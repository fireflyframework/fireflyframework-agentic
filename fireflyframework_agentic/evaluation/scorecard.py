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
"""Scorecard renderer: gate results -> Markdown report.

Every scorecard states whether it is self-graded.  Until Phase 3 independent
re-annotation lands, all Lean-Core PROMOTE verdicts are self-graded against
team-authored ground truth.  See EVALUATION_FRAMEWORK.md.
"""

from __future__ import annotations

import json

VERDICT_PROMOTE = "PROMOTE"
VERDICT_HOLD = "HOLD"


def verdict(gate_results: list) -> str:
    """PROMOTE iff all gates passed and G5 is in the list; HOLD otherwise."""
    if not gate_results:
        return VERDICT_HOLD
    if not all(g.passed for g in gate_results):
        return VERDICT_HOLD
    gate_names = {g.gate for g in gate_results}
    if "G5" not in gate_names:
        return VERDICT_HOLD
    return VERDICT_PROMOTE


def render_scorecard(
    gate_results: list,
    *,
    corpus: str = "unknown",
    model_id: str = "unknown",
    run_id: str = "run",
    is_self_graded: bool = True,
    kappa_advisory: bool = False,
    evidence_unverified: bool = False,
    bpi2017_f1: float | None = None,
    advisory=None,
    config: dict | None = None,
    experiment_config: dict | None = None,
) -> str:
    """Render a Markdown evaluation scorecard.

    The scorecard always discloses self-graded status and advisory flags.
    """
    v = verdict(gate_results)
    lines = [
        "# FlyRadar Evaluation Scorecard",
        "",
        f"**Corpus**: {corpus}",
        f"**Model**: {model_id}",
        f"**Run**: {run_id}",
        f"**Verdict**: **{v}**",
        "",
    ]

    if is_self_graded:
        lines += [
            "> **SELF-GRADED**: All ground truth (must-find, gold, DILO, human sign-off) is",
            "> authored by the FlyRadar team.  This PROMOTE has no contamination-free signal",
            "> until Phase 3.  See EVALUATION_FRAMEWORK.md.",
            "",
        ]

    if kappa_advisory:
        lines += [
            "> **ADVISORY**: Registry kappa < 0.70 — a second independent annotator has not",
            "> verified the must-find items.  Promotion is advisory for this corpus until",
            "> kappa >= 0.70 from an independent re-annotation.",
            "",
        ]

    if evidence_unverified:
        lines += [
            "> **EVIDENCE UNVERIFIED**: no corpus supplied (--corpus) — evidence locators",
            "> and excerpts are taken at face value from the run's own evidence_index.",
            "> Grounding certifies self-consistency, not corpus reality.  Supply the run's",
            "> input.json to enable deterministic excerpt verification (G3, §6.3).",
            "",
        ]

    if experiment_config is not None:
        lines += [
            "## Experiment configuration",
            "How this run was generated. Recorded fields (cost, tokens, latency, agents) are "
            "read from the run's output.json; `model` is the value passed to the harness via "
            "--model-id. Generation params (temperature, prompt/pipeline version, seed) are not "
            "captured in output.json.",
            "",
            "```json",
            json.dumps(experiment_config, indent=2, default=str),
            "```",
            "",
        ]

    if config is not None:
        lines += [
            "## Evaluation configuration",
            "These are the parameters used to compute the evaluation.",
            "",
            "```json",
            json.dumps(config, indent=2, default=str),
            "```",
            "",
        ]

    lines += ["## Gate Results", ""]
    g5_result = None
    for g in gate_results:
        if g.gate == "G5":
            g5_result = g
            continue
        status = "PASS" if g.passed else f"FLAG ({g.reason_code})"
        lines.append(f"### {g.gate}: {status}")
        if g.details:
            lines.append("```json")
            lines.append(json.dumps(g.details, indent=2, default=str))
            lines.append("```")
        lines.append("")

    if bpi2017_f1 is not None:
        ok = bpi2017_f1 >= 0.60
        anchor_status = "PASS (>= 0.60)" if ok else "BELOW THRESHOLD (< 0.60)"
        lines += [
            "## External Sanity Anchor (non-blocking)",
            f"BPI-2017 variant-recovery F1: **{bpi2017_f1:.3f}** — {anchor_status}",
            "_One non-self-graded signal.  Non-blocking; informational only._",
            "",
        ]

    if advisory is not None:
        lines += _render_advisory(advisory)

    if g5_result is not None:
        status = "PASS" if g5_result.passed else f"FLAG ({g5_result.reason_code})"
        lines.append(f"### G5: {status}")
        if g5_result.details:
            lines.append("```json")
            lines.append(json.dumps(g5_result.details, indent=2, default=str))
            lines.append("```")
        lines.append("")

    lines += _render_analysis(gate_results, advisory)

    return "\n".join(lines)


def _num(x) -> str:
    """Format a metric leaf: None -> 'n/a', float -> 3dp, else str."""
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def _render_advisory(report) -> list[str]:
    """Render the non-blocking G4 LLM-as-a-Judge section from an AdvisoryReport.

    Best-effort: only metrics present in report.metrics are shown.  G4 never
    affects the PROMOTE/HOLD verdict; this section is decision-support for the
    G5 human sign-off, and is advisory until LLM-as-a-Judge calibration (§10).
    """
    m = report.metrics
    cal = "calibrated" if report.calibrated else "uncalibrated"
    lines = [
        "## G4 — LLM-as-a-Judge (non-blocking — does NOT affect the PROMOTE/HOLD verdict)",
        f"Judge: {report.judge_model} · {cal} · {report.runs}-run median",
    ]
    if report.same_provider_caveat:
        lines.append("> same-provider as the pipeline — results may share blind spots.")
    lines.append("```text")

    if "faithfulness" in m:
        d = m["faithfulness"]
        u = d.get("unsupported_ids", [])
        extra = f"   (unsupported: {', '.join(u)})" if u else ""
        lines.append(f"Faithfulness (entailment):       {d.get('supported')}/{d.get('total')} supported{extra}")
    if "numeric_temporal_fidelity" in m:
        lines.append(f"Numeric/temporal fidelity:       {m['numeric_temporal_fidelity'].get('count', 0)} mismatch(es)")
    if "citation_relevance" in m:
        d = m["citation_relevance"]
        lines.append(
            f"Citation relevance (ctx-prec):   {_num(d.get('precision'))}   ({d.get('relevant')}/{d.get('total')})"
        )
    if "semantic_recovery" in m:
        d = m["semantic_recovery"]
        rec = d.get("recovered", [])
        rids = ", ".join(r.get("id", "") for r in rec) if rec else "none"
        lines.append(
            f"Semantic recovery (ctx-recall):  lexical {_num(d.get('lexical_recall'))} -> {_num(d.get('recovered_recall'))}   (recovered: {rids})"
        )
    if "nc_semantic_precision" in m:
        d = m["nc_semantic_precision"]
        a = d.get("asserted_ids", [])
        extra = f"   ({', '.join(a)})" if a else ""
        lines.append(f"NC semantic precision:           {d.get('asserted', 0)} asserted{extra}")
    if "fabricated_entity" in m:
        lines.append(f"Fabricated-entity check:         {m['fabricated_entity'].get('count', 0)}")
    if "contradiction" in m:
        lines.append(f"Contradiction detection:         {m['contradiction'].get('count', 0)}")
    if "actionability" in m:
        d = m["actionability"]
        lines.append(f"Actionability:                   {_num(d.get('score'))}   (rated {d.get('rated', 0)})")
    if "severity_calibration" in m:
        d = m["severity_calibration"]
        lines.append(f"Severity calibration:            {d.get('miscalibrated', 0)}/{d.get('total', 0)} miscalibrated")
    if "answer_relevancy" in m:
        lines.append(f"Answer relevancy:                {_num(m['answer_relevancy'].get('score'))}")
    if "comparative_vs_champion" in m:
        lines.append(
            f"Comparative vs champion:         more consistent -> {m['comparative_vs_champion'].get('more_consistent', 'n/a')}"
        )
    if "source_coverage" in m:
        d = m["source_coverage"]
        o = d.get("orphaned", [])
        extra = f"   (orphaned: {', '.join(o)})" if o else ""
        lines.append(f"Source coverage [D]:             {d.get('cited')}/{d.get('total')} documents cited{extra}")
    if "excerpt_fill_rate" in m:
        d = m["excerpt_fill_rate"]
        lines.append(f"Evidence-excerpt fill [D]:       {d.get('populated')}/{d.get('total')} populated")
    if "open_gap" in m:
        gap = (m["open_gap"].get("gap") or "").strip()
        if gap:
            lines.append(f"Open gap probe:                  {gap}")
    if report.errors:
        lines.append(f"(errors: {len(report.errors)} metric(s) failed: {'; '.join(report.errors)})")
    lines.append("```")
    # Full detail — nothing truncated: every id, pair, verdict, and complete text.
    lines += [
        "",
        "**G4 — full metric detail:**",
        "```json",
        json.dumps({"metrics": report.metrics, "details": report.details}, indent=2, default=str),
        "```",
    ]
    lines.append("> Decision support for the G5 human sign-off; advisory until LLM-as-a-Judge calibration (§10).")
    lines.append("")
    return lines


def _render_analysis(gate_results: list, advisory=None) -> list[str]:
    """Render a plain-language interpretation of all evaluation signals."""
    g2 = next((g for g in gate_results if g.gate == "G2"), None)
    g3 = next((g for g in gate_results if g.gate == "G3"), None)

    lines = ["## Analysis", ""]

    # ── Topic coverage (G2) ──────────────────────────────────────────────────
    lines.append("### Topic coverage (G2)")
    if g2 and g2.details:
        d = g2.details
        recall = d.get("recall", 0.0)
        tiers = d.get("per_tier", {})
        finding_count = d.get("finding_count", 0)
        redundancy = d.get("finding_redundancy_rate", 0.0)
        matched = d.get("findings_matched_to_registry", {}).get("fraction", 0.0)

        tier_summary = ", ".join(
            f"{t} {v['hit']}/{v['total']}" for t, v in tiers.items() if "hit" in v and "total" in v
        )
        lines.append(
            f"Lexical recall is **{recall:.3f}** ({tier_summary}). "
            f"The run produced {finding_count} findings, "
            f"all of which map to a registry item (match rate {matched:.0%}). "
        )
        if redundancy > 0.15:
            lines.append(
                f"Finding redundancy is **{redundancy:.0%}** — a meaningful share of "
                "findings are near-duplicates of each other (Jaccard ≥ 0.6). "
                "The run is covering the same ground multiple times rather than broadening coverage."
            )
        else:
            lines.append(f"Finding redundancy is low ({redundancy:.0%}): each finding addresses a distinct topic.")
        lines.append(
            "_G2 is a topic-level test. A recall of 1.000 means every required topic was "
            "mentioned somewhere — it does not verify that the specific claims about those "
            "topics are accurate. Claim accuracy is G4 Faithfulness._"
        )
    else:
        lines.append("G2 result unavailable.")
    lines.append("")

    # ── Evidence quality (G3) ────────────────────────────────────────────────
    lines.append("### Evidence quality (G3)")
    if g3 and g3.details:
        d = g3.details
        grounding = d.get("grounding_pct", 0.0)
        ev = d.get("evidence_verification", {})
        verified = ev.get("verified", 0)
        entries = ev.get("entries", 0)
        fabricated = ev.get("fabricated", [])
        unknown = ev.get("source_unknown", [])
        orphaned = d.get("orphaned_sources", [])
        source_cov = d.get("source_coverage", "")

        lines.append(
            f"Grounding is **{grounding:.0%}**: every finding cites at least one "
            "corpus document, and all excerpts are populated. "
            f"Evidence verification checked {entries} entries against the raw corpus: "
            f"{verified} verified"
            + (f", **{len(fabricated)} fabricated** (locators that do not exist in the corpus)" if fabricated else "")
            + (f", **{len(unknown)} source-unknown** (locators that resolve to no corpus file)" if unknown else "")
            + "."
        )
        if unknown:
            lines.append(
                f"The source-unknown locator(s) are: `{'`, `'.join(unknown)}`. "
                "This is most likely a corpus bundle gap rather than a hallucinated source — "
                "verify that all expected files are included in `input.json`."
            )
        if orphaned:
            lines.append(
                f"**{len(orphaned)} corpus documents were never cited** by this run "
                f"({', '.join(orphaned)}). These are blind spots: the run extracted nothing "
                "from these sources, so any findings they contain are silently missed."
            )
        if source_cov:
            cited, total = (int(x) for x in source_cov.split("/"))
            if cited < total:
                lines.append(
                    f"Overall source coverage is {cited}/{total} — "
                    f"{total - cited} corpus file(s) left entirely uncited."
                )
    else:
        lines.append("G3 result unavailable.")
    lines.append("")

    # ── Claim accuracy (G4) ──────────────────────────────────────────────────
    if advisory is not None:
        m = advisory.metrics
        lines.append("### Claim accuracy (G4 — advisory)")

        faith = m.get("faithfulness", {})
        supported = faith.get("supported", 0)
        total_f = faith.get("total", 0)
        if total_f:
            faith_pct = supported / total_f
            lines.append(
                f"**Faithfulness: {supported}/{total_f} findings ({faith_pct:.0%}) are entailed by their cited evidence.** "
            )
            if faith_pct < 0.5:
                lines.append(
                    "This is a critical signal: the majority of findings contain claims "
                    "that the judge cannot verify from the cited sources. "
                    "The run is presenting inferences, extrapolations, or hallucinated details "
                    "as if they were directly evidenced. "
                    "Each unsupported finding should be reviewed against its cited document before use."
                )
            elif faith_pct < 0.8:
                lines.append(
                    "A significant minority of findings contain claims not traceable to cited sources. "
                    "These may be reasonable inferences, but they should be flagged for human verification."
                )
            else:
                lines.append("Most findings are directly supported by their cited evidence.")

        ntf = m.get("numeric_temporal_fidelity", {})
        mismatch_count = ntf.get("count", 0)
        if mismatch_count:
            lines.append(
                f"**Numeric/temporal fidelity: {mismatch_count} mismatches detected.** "
                "Specific figures — FTE costs, durations, timestamps, percentages, case IDs — "
                "appear in findings but cannot be traced to the cited evidence. "
                "These numbers should be treated as estimates or fabrications until verified "
                "against the source documents."
            )

        fab = m.get("fabricated_entity", {})
        fab_count = fab.get("count", 0)
        fab_entities = fab.get("entities", [])
        if fab_count:
            lines.append(
                f"**Fabricated entities: {fab_count}** — the following names/identifiers appear "
                f"in the output but are absent from the corpus: "
                f"{', '.join(f'`{e}`' for e in fab_entities)}. "
                "These should be removed or verified before sharing the output."
            )

        sev = m.get("severity_calibration", {})
        misc = sev.get("miscalibrated", 0)
        total_s = sev.get("total", 0)
        verdicts = sev.get("verdicts", {})
        over_count = sum(1 for v in verdicts.values() if v == "over")
        under_count = sum(1 for v in verdicts.values() if v == "under")
        if misc and total_s:
            direction = ""
            if over_count > under_count:
                direction = f" (predominantly over-rated: {over_count} findings rated too high)"
            elif under_count > over_count:
                direction = f" (predominantly under-rated: {under_count} findings rated too low)"
            lines.append(
                f"**Severity calibration: {misc}/{total_s} findings miscalibrated{direction}.** "
                "Over-rated findings inflate perceived urgency and can cause the client to "
                "prioritise the wrong items."
            )

        act = m.get("actionability", {})
        act_score = act.get("score")
        if act_score is not None:
            if act_score < 0.6:
                lines.append(
                    f"**Actionability score: {act_score:.3f}** — proposed actions are below the "
                    "0.6 threshold for concrete, quantified recommendations. "
                    "Actions tend to be generic rather than specific enough to assign and execute."
                )
            else:
                lines.append(f"Actionability score: {act_score:.3f} — actions are sufficiently concrete.")

        og = m.get("open_gap", {})
        gap_text = (og.get("gap") or "").strip()
        if gap_text:
            lines.append(f"**Most important missed finding:** {gap_text}")

        lines.append("")

    # ── Bottom line ──────────────────────────────────────────────────────────
    lines.append("### Bottom line")
    g5 = next((g for g in gate_results if g.gate == "G5"), None)
    g5_reason = (g5.details or {}).get("reason", "") if g5 else ""
    flags = [g for g in gate_results if not g.passed]
    flag_names = [g.gate for g in flags]

    if not flags:
        lines.append("All deterministic gates pass. The run is ready for G5 human sign-off.")
    else:
        flag_str = ", ".join(flag_names)
        lines.append(f"The run is at **HOLD** due to flags on: {flag_str}. ")
        for g in flags:
            if g.gate == "G3" and g.reason_code == "EVIDENCE_SOURCE_UNKNOWN":
                lines.append(
                    "- **G3**: One evidence locator points to a file not in the corpus bundle. "
                    "Regenerate `input.json` to include all corpus sources, then re-run."
                )
            elif g.gate == "G5":
                lines.append(f"- **G5**: {g5_reason}")

    if advisory is not None:
        m = advisory.metrics
        faith = m.get("faithfulness", {})
        supported = faith.get("supported", 0)
        total_f = faith.get("total", 1)
        ntf_count = m.get("numeric_temporal_fidelity", {}).get("count", 0)
        fab_count = m.get("fabricated_entity", {}).get("count", 0)
        lines.append(
            f"\nG4 advisory signals (non-blocking but important for the G5 reviewer): "
            f"faithfulness {supported}/{total_f}, "
            f"{ntf_count} numeric mismatches, "
            f"{fab_count} fabricated entities. "
            "The G5 reviewer should focus on the unsupported findings and verify figures "
            "against the source documents before certifying the output."
        )
    lines.append("")
    return lines
