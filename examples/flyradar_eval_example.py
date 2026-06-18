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

"""FlyRadar evaluation example — gate-based process-mining quality gate.

Demonstrates how to use ``fireflyframework_agentic.evaluation`` to replicate
the flyradar experiment quality-gate workflow:

1. Load a must-find registry (the gold standard items the model must discover).
2. Load a DiscoveryResult produced by a flyradar pipeline run.
3. Run gates G1-G5 to produce a structured verdict:
     G1 -- Structural & Safe (schema validity, PII, empty-registry guard).
     G2 -- Recall & Precision (must-find recall floor, NC precision).
     G3 -- Grounded (finding-to-evidence anchoring).
     G4 -- LLM-as-a-Judge (advisory only; never blocks promotion).
     G5 -- No-regression / promotion (champion/challenger comparison).
4. Render a human-readable scorecard and print the final verdict.
5. Promote the challenger to champion when the verdict is PROMOTE.

Usage::

    # Minimal: deterministic gates only (no G4 judge, no baseline)
    python examples/flyradar_eval_example.py \\
        --result output.json \\
        --registry registry.json

    # With corpus verification and a champion baseline
    python examples/flyradar_eval_example.py \\
        --result output.json \\
        --registry registry.json \\
        --baseline baseline.json \\
        --corpus input.json

    # With the advisory G4 LLM judge (requires API key in environment)
    FLYEVAL_JUDGE_MODEL=anthropic:claude-sonnet-4-6 \\
    python examples/flyradar_eval_example.py \\
        --result output.json \\
        --registry registry.json \\
        --judge-model anthropic:claude-sonnet-4-6

Exit codes: 0 = PROMOTE, 1 = HOLD.

Input file formats
------------------
``--result`` (output.json)
    A DiscoveryResult JSON produced by a flyradar pipeline run.  Must contain
    at minimum ``findings`` (list) and ``evidence_index`` (list).

``--registry`` (registry.json)
    A lean-1 registry JSON.  Each item has ``id``, ``tier`` (L0-L3), ``title``,
    ``description``, and ``nc`` (bool, True for negative controls).

``--baseline`` (baseline.json)
    A ChampionRecord JSON written by a previous PROMOTE run.  When omitted the
    gate runs in day-zero mode (G5 always passes and a new champion is minted).

``--corpus`` (input.json)
    The corpus bundle used during the run.  When supplied, G3 verifies that cited
    evidence excerpts actually appear in the corpus documents.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fireflyframework_agentic.evaluation import (
    ChampionRecord,
    GateResult,
    build_embedder,
    load_champion,
    load_corpus,
    load_registry,
    render_scorecard,
    run_gates,
    run_judge,
    save_champion,
    verdict,
    VERDICT_PROMOTE,
)
from fireflyframework_agentic.evaluation.models import EvalConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: str) -> dict:
    """Read a JSON file and return its contents as a dict."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _lexical_missed_ids(result: dict, registry) -> list[str]:
    """Return the IDs of registry items not matched by any finding (lexically).

    The G4 judge uses these to focus its coverage checks on items that
    lexical recall missed — the places where semantic recovery matters most.
    """
    from fireflyframework_agentic.evaluation.matcher import matches

    evidence_index = {ev["id"]: ev for ev in result.get("evidence_index", []) if ev.get("id")}
    findings = result.get("findings", [])
    # L3 items are informational-only and are never scored.
    scored_items = [item for item in registry.real_items if item.tier != "L3"]
    return [
        item.id
        for item in scored_items
        if not any(matches(f, item, evidence_index) for f in findings)
    ]


# ---------------------------------------------------------------------------
# Main evaluation flow
# ---------------------------------------------------------------------------


def run_evaluation(args: argparse.Namespace) -> int:
    """Run the full flyradar gate evaluation and return an exit code."""

    # ------------------------------------------------------------------
    # Step 1 — Load inputs.
    # ------------------------------------------------------------------
    print(f"Loading result   : {args.result}")
    result = _load_json(args.result)

    print(f"Loading registry : {args.registry}")
    registry = load_registry(args.registry)
    print(f"  {len(registry.real_items)} real items, {len(registry.nc_items)} NC items")

    # The EvalConfig captures provenance for the run record.
    config = EvalConfig(
        model_id=args.model_id,
        corpus=registry.corpus,
        run_id=args.run_id,
        registry_path=args.registry,
        corpus_path=args.corpus or "",
        baseline_path=args.baseline or "",
        judge_model=args.judge_model or "",
    )

    # Optional: corpus bundle for deterministic evidence verification (G3).
    corpus = None
    if args.corpus:
        print(f"Loading corpus   : {args.corpus}")
        corpus = load_corpus(args.corpus)

    # Optional: champion record for regression detection (G5).
    champion = None
    champion_scores = None
    aa_noise = None
    if args.baseline:
        print(f"Loading baseline : {args.baseline}")
        champion = load_champion(args.baseline)
        if champion:
            champion_scores = champion.scores
            aa_noise = champion.aa_noise
            print(f"  Champion run   : {champion.run_id} ({champion.model_id})")
        else:
            print("  No champion found — running in day-zero mode.")

    # Optional: embedder for semantic/hybrid recall (G2).
    embed_fn = None
    if args.embedder:
        print(f"Building embedder: {args.embedder}")
        embed_fn = build_embedder(args.embedder)

    print()

    # ------------------------------------------------------------------
    # Step 2 — Run deterministic gates G1-G3 + G5.
    #
    # run_gates() returns a list of GateResult objects, one per gate.
    # Each GateResult carries:
    #   .gate   -- "G1" | "G2" | "G3" | "G5"
    #   .passed -- bool
    #   .details -- dict with per-metric values
    #   .errors  -- list[str] of blocking error codes
    # ------------------------------------------------------------------
    print("Running gates G1-G3 + G5 ...")
    gate_results: list[GateResult] = run_gates(
        result,
        registry,
        args.registry,
        pii_list=args.pii_list or [],
        recall_floor=args.recall_floor,
        grounding_floor=args.grounding_floor,
        champion_scores=champion_scores,
        aa_noise=aa_noise,
        is_day_zero=(champion is None),
        human_signed_off=args.human_signed_off,
        signoff_count=args.signoffs,
        embed_fn=embed_fn,
        tau=args.tau,
        recall_metric=args.recall_metric,
        tau_nc=args.tau_nc,
        corpus=corpus,
    )

    # Quick gate summary before the full scorecard.
    for gr in gate_results:
        status = "PASS" if gr.passed else "FAIL"
        print(f"  {gr.gate}: {status}")

    # ------------------------------------------------------------------
    # Step 3 — Run the advisory G4 LLM-as-a-Judge (optional).
    #
    # G4 is non-blocking: it never changes the verdict or exit code.
    # It produces an AdvisoryReport with per-finding quality signals
    # (faithfulness, citation relevance, fabricated entities, etc.).
    # ------------------------------------------------------------------
    advisory = None
    if args.judge_model:
        print(f"\nRunning G4 judge ({args.judge_model}) ...")
        missed_ids = _lexical_missed_ids(result, registry)
        advisory = run_judge(
            result,
            registry,
            judge_model=args.judge_model,
            runs=args.judge_runs,
            concurrency=args.judge_concurrency,
            pipeline_model=args.model_id,
            embed_fn=embed_fn,
            tau=args.tau,
            lexical_missed_ids=missed_ids,
        )
        print(f"  Judge completed ({args.judge_runs} run(s)).")
    else:
        print("\nG4 judge skipped (pass --judge-model to enable).")

    # ------------------------------------------------------------------
    # Step 4 — Render the scorecard.
    #
    # render_scorecard() produces a markdown-formatted human-readable
    # report that mirrors the output of `flyeval gate` in the playground.
    # ------------------------------------------------------------------
    print()
    scorecard = render_scorecard(
        gate_results,
        corpus=registry.corpus,
        model_id=config.model_id,
        run_id=config.run_id,
        is_self_graded=True,
        kappa_advisory=registry.is_kappa_advisory(),
        evidence_unverified=(corpus is None),
        advisory=advisory,
    )
    print(scorecard)

    # ------------------------------------------------------------------
    # Step 5 — Inspect the verdict and handle promotion.
    #
    # verdict() returns "PROMOTE" or "HOLD" based on the gate results.
    # On PROMOTE, save the challenger as the new champion so future runs
    # can detect regressions against this baseline.
    # ------------------------------------------------------------------
    v = verdict(gate_results)
    print(f"\nFinal verdict: {v}")

    if v == VERDICT_PROMOTE and args.baseline:
        # Extract the key scores from G2 and G3 to store in the champion record.
        g2 = next((g for g in gate_results if g.gate == "G2"), None)
        g3 = next((g for g in gate_results if g.gate == "G3"), None)
        scores: dict[str, float] = {}
        if g2:
            scores["recall"] = g2.details.get("recall", 0.0)
        if g3:
            scores["grounding_pct"] = g3.details.get("grounding_pct", 0.0)

        new_champion = ChampionRecord(
            corpus=registry.corpus,
            run_id=config.run_id,
            model_id=config.model_id,
            registry_sha256=registry.sha256(),
            scores=scores,
            is_day_zero=(champion is None),
        )
        save_champion(
            args.baseline,
            new_champion,
            summary=f"Promoted by flyradar_eval_example.py — {config.run_id}",
        )
        print(f"Champion saved to {args.baseline}")

    # Exit 0 = PROMOTE, 1 = HOLD (mirrors `flyeval gate` convention).
    return 0 if v == VERDICT_PROMOTE else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flyradar_eval_example",
        description="FlyRadar gate evaluation — replicates the flyeval gate workflow.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Required inputs.
    p.add_argument("--result", required=True, help="Path to DiscoveryResult JSON.")
    p.add_argument("--registry", required=True, help="Path to lean-1 registry JSON.")

    # Optional inputs.
    p.add_argument(
        "--baseline",
        help="Path to baseline.json (champion store).  When absent, runs in day-zero mode.",
    )
    p.add_argument(
        "--corpus",
        help="Path to input.json corpus bundle for deterministic evidence verification (G3).",
    )

    # Run metadata.
    p.add_argument("--model-id", default="unknown", help="Model identifier for the scorecard.")
    p.add_argument("--run-id", default="example-run", help="Run identifier for the scorecard.")

    # Gate thresholds.
    p.add_argument(
        "--recall-floor",
        type=float,
        default=0.70,
        help="Minimum recall required for G2 to pass.",
    )
    p.add_argument(
        "--grounding-floor",
        type=float,
        default=0.90,
        help="Minimum grounding percentage required for G3 to pass.",
    )
    p.add_argument(
        "--recall-metric",
        choices=["lexical", "semantic", "hybrid"],
        default="lexical",
        help="Recall metric used by G2.  'semantic' and 'hybrid' require --embedder.",
    )
    p.add_argument(
        "--tau",
        type=float,
        default=0.70,
        help="Cosine similarity threshold for semantic recall (real items).",
    )
    p.add_argument(
        "--tau-nc",
        type=float,
        default=0.85,
        help="Cosine similarity threshold for NC item detection.",
    )
    p.add_argument("--pii-list", nargs="*", default=[], help="PII tokens to check for in findings.")
    p.add_argument("--human-signed-off", action="store_true", help="Mark this run as human-reviewed.")
    p.add_argument("--signoffs", type=int, default=0, help="Number of human sign-offs collected.")

    # G4 judge options.
    p.add_argument(
        "--judge-model",
        default=None,
        help=(
            "Provider:model string for the advisory G4 LLM judge "
            "(e.g. 'anthropic:claude-sonnet-4-6').  Omit to skip G4."
        ),
    )
    p.add_argument(
        "--judge-runs",
        type=int,
        default=1,
        help="Number of judge calls to aggregate (odd number recommended for median).",
    )
    p.add_argument(
        "--judge-concurrency",
        type=int,
        default=1,
        help="Thread fan-out for per-item G4 metrics (1 = sequential).",
    )

    # Embedder for semantic recall.
    p.add_argument(
        "--embedder",
        default=None,
        help="Embedder spec for semantic/hybrid recall (e.g. 'ollama:bge-m3').",
    )

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run_evaluation(args))


if __name__ == "__main__":
    main()
