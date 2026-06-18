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
"""flyeval — FlyRadar Lean Core evaluation CLI.

Usage
-----
    flyeval gate      --result R.json --registry REG.json [--baseline B.json] [--judge-model P:M]
    flyeval aa-band   --results R1.json R2.json ... --registry REG.json
    flyeval day-zero  --result R.json --registry REG.json --baseline B.json --signoffs 2
    flyeval invalidate --baseline B.json --reason "..."

The deterministic gates G1-G3 + G5 (human sign-off) decide the verdict: every
subcommand exits 0 on PROMOTE, 1 on HOLD.  G4 (the --judge-model LLM-as-a-Judge,
on by default, --no-judge to skip) is non-blocking — it prints advisory signals
and never changes the verdict or the exit code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from fireflyframework_agentic.evaluation import __version__
from fireflyframework_agentic.evaluation.champion import (
    ChampionRecord,
    invalidate_champion,
    load_champion,
    save_champion,
)
from fireflyframework_agentic.evaluation.corpus import load_corpus
from fireflyframework_agentic.evaluation.gates import g2_recall_precision, run_gates
from fireflyframework_agentic.evaluation.judge import run_judge
from fireflyframework_agentic.evaluation.judge_client import build_embedder
from fireflyframework_agentic.evaluation.matcher import matches
from fireflyframework_agentic.evaluation.registry import load_registry
from fireflyframework_agentic.evaluation.scorecard import render_scorecard, verdict as get_verdict
from fireflyframework_agentic.evaluation.stats import aa_band, left_skew_flag


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _lexical_missed_ids(result: dict, registry) -> list[str]:
    """Scored (non-L3) real-item ids matched by no finding — the G2 lexical misses G4 recovers."""
    evidence_index = {ev["id"]: ev for ev in result.get("evidence_index", []) if ev.get("id")}
    findings = result.get("findings", [])
    scored = [i for i in registry.real_items if i.tier != "L3"]
    return [i.id for i in scored if not any(matches(f, i, evidence_index) for f in findings)]


def _read_experiment_config(result_path: str) -> dict | None:
    """Read the experiment_configuration.json recorded next to the run's output.json.

    The experiment config records how the run was generated; it is authored by the
    generation step at run time.  Evaluation only reads it for display and never
    writes or overwrites it.  Returns None when the run has no recorded config.
    """
    path = Path(result_path).parent / "experiment_configuration.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_eval_config(result_path: str, config: dict) -> Path:
    """Write evaluation_configuration.json next to the run's output.json.

    The evaluation config is authored by flyeval at gate time (registry/corpus SHAs,
    recall metric, floors, judge settings), so unlike the experiment config it is
    owned here and safe to (over)write each run.  It mirrors the block embedded in
    the scorecard, as a machine-readable artifact.
    """
    path = Path(result_path).parent / "evaluation_configuration.json"
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _eval_config(args, registry, corpus=None) -> dict:
    """Capture the run's evaluation configuration for provenance.

    Uses getattr defaults so it works for both `gate` (has every flag) and
    `day-zero` (lacks the gate-only flags, falling back to the lexical/no-judge
    defaults, which honestly reflects how day-zero scores).
    """
    jm = getattr(args, "judge_model", None)
    baseline = getattr(args, "baseline", None)
    tau = getattr(args, "tau", 0.70)
    return {
        "evaluator_version": __version__,
        "registry_sha256": registry.sha256(),
        "corpus_sha256": corpus.sha256 if corpus else None,
        "model_id": getattr(args, "model_id", None) or "unknown",
        "gates": {
            "G1": {
                "name": "Structural & Safe",
                "pii_list": getattr(args, "pii_list", None) or [],
                "metrics": {
                    "empty_must_find": "registry has >=1 must-find item; guards the fake-100% "
                    "champion (EMPTY_MUST_FIND)",
                    "registry_sha256_pin": "loaded registry matches its file hash (GOLD_DRIFT)",
                    "corpus_sha256_pin": "corpus matches its hash when supplied (CORPUS_DRIFT)",
                    "schema_valid": "required top-level keys present in the result "
                    "(SCHEMA_INVALID)",
                    "pii_non_disclosure": "no corpus PII name appears in any finding/report text "
                    "(PII_LEAK)",
                },
            },
            "G2": {
                "name": "Recall & Precision",
                "recall_metric": getattr(args, "recall_metric", "lexical"),
                "recall_floor": getattr(args, "recall_floor", 0.70),
                "tau": tau,
                "tau_nc": getattr(args, "tau_nc", 0.85),
                "embedder": getattr(args, "embedder", None),
                "metrics": {
                    "lexical_recall": "token-overlap recall (always reported)",
                    "semantic_recall": "embedding-similarity recall at >= tau (needs embedder)",
                    "hybrid_recall": "per item, a lexical OR semantic match",
                    "per_tier_recall": "hit/total per tier L0-L3; an L0 miss blocks",
                    "nc_precision": "negative-control items wrongly emitted; an NC hit blocks",
                    "finding_redundancy_rate": "fraction of findings duplicating another's topic",
                },
            },
            "G3": {
                "name": "Grounded",
                "grounding_floor": getattr(args, "grounding_floor", 0.90),
                "human_spot_check_n": 5,
                "corpus_verification": corpus is not None,
                "metrics": {
                    "grounding_pct": "findings whose cited excerpt shares a topic token; blocks "
                    "below grounding_floor",
                    "evidence_verified": "cited excerpts located in the actual corpus "
                    "(when supplied)",
                    "evidence_fabricated": "populated excerpts not found in their cited source "
                    "(EVIDENCE_FABRICATED)",
                    "evidence_source_unknown": "locators resolving to no corpus document "
                    "(EVIDENCE_SOURCE_UNKNOWN)",
                    "excerpt_fill_rate": "evidence entries carrying a populated excerpt",
                    "source_coverage": "distinct corpus documents cited",
                },
            },
            "G4": {
                "name": "LLM Judge (advisory, non-blocking)",
                "judge_model": jm,
                "judge_runs": getattr(args, "judge_runs", 1) if jm else None,
                "judge_concurrency": getattr(args, "judge_concurrency", 1) if jm else None,
                "judge_temperature": 0.0 if jm else None,
                "tau": tau if jm else None,
                "metrics": {
                    "faithfulness": "each finding's claim entailed by its cited evidence",
                    "numeric_temporal_fidelity": "numbers and dates in findings match the evidence",
                    "citation_relevance": "cited evidence refs are on-topic (context precision)",
                    "nc_semantic_precision": "negative-control items semantically asserted",
                    "fabricated_entity": "named entities absent from the corpus",
                    "contradiction": "findings contradicting the evidence or each other",
                    "open_gap": "a consequential issue the output failed to surface",
                    "actionability": "proposed actions are specific and actionable",
                    "severity_calibration": "stated severity matches the evidence",
                    "answer_relevancy": "output addresses the workspace intention",
                    "source_coverage": "distinct corpus documents cited (deterministic)",
                    "excerpt_fill_rate": "evidence entries with a populated excerpt "
                    "(deterministic)",
                },
            },
            "G5": {
                "name": "No-regression / promotion",
                "is_day_zero": baseline is None,
                "human_signed_off": getattr(args, "human_signed_off", False),
                "signoffs": getattr(args, "signoffs", 0),
                "baseline": baseline,
                "baseline_sha256": _file_sha256(baseline) if baseline else None,
                "metrics": {
                    "improvements": "metrics beating the champion by more than the AA noise band",
                    "regressions": "metrics that regressed versus the champion",
                    "noise_band": "per-metric AA noise floor a candidate must exceed",
                    "guardrail_regression": "any guardrail metric that dropped",
                    "signoffs": "independent human sign-offs recorded",
                },
            },
        },
    }


def _file_sha256(path: str) -> str | None:
    """SHA-256 of a file's bytes, or None when it can't be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


# ── gate ──────────────────────────────────────────────────────────────────────


def cmd_gate(args: argparse.Namespace) -> int:
    if getattr(args, "no_judge", False):
        args.judge_model = None  # explicit opt-out; G4 runs by default otherwise
    result = _load_json(args.result)
    registry = load_registry(args.registry)
    corpus = load_corpus(args.corpus) if args.corpus else None
    champion = load_champion(args.baseline) if args.baseline else None
    champion_scores = champion.scores if champion else None
    aa_noise = champion.aa_noise if champion else None

    embed_fn = build_embedder(args.embedder) if args.embedder else None

    if args.recall_metric in ("hybrid", "semantic") and embed_fn is None:
        print(
            f"ERROR: --recall-metric {args.recall_metric} requires --embedder.\n"
            "  Example: --embedder openai:text-embedding-3-small",
            file=sys.stderr,
        )
        return 2

    gate_results = run_gates(
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

    # G4 — on by default, non-blocking.  Skipped only with --no-judge; never affects the verdict.
    advisory = None
    if args.judge_model:
        champion_result = _load_json(args.champion_result) if args.champion_result else None
        advisory = run_judge(
            result,
            registry,
            judge_model=args.judge_model,
            runs=args.judge_runs,
            concurrency=args.judge_concurrency,
            pipeline_model=args.model_id or "",
            champion_result=champion_result,
            embed_fn=embed_fn,
            tau=args.tau,
            lexical_missed_ids=_lexical_missed_ids(result, registry),
        )

    config = _eval_config(args, registry, corpus)
    _write_eval_config(args.result, config)
    experiment_config = _read_experiment_config(args.result)
    scorecard = render_scorecard(
        gate_results,
        corpus=registry.corpus,
        model_id=args.model_id or "unknown",
        run_id=args.run_id or "run",
        is_self_graded=True,
        kappa_advisory=registry.is_kappa_advisory(),
        evidence_unverified=corpus is None,
        advisory=advisory,
        config=config,
        experiment_config=experiment_config,
    )
    print(scorecard)

    v = get_verdict(gate_results)
    return 0 if v == "PROMOTE" else 1


# ── aa-band ───────────────────────────────────────────────────────────────────


def cmd_aa_band(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)

    if args.recall_metric in ("hybrid", "semantic") and not args.embedder:
        print(
            f"ERROR: --recall-metric {args.recall_metric} requires --embedder.\n"
            "  Example: --embedder openai:text-embedding-3-small",
            file=sys.stderr,
        )
        return 2

    embed_fn = build_embedder(args.embedder) if args.embedder else None
    corpus = load_corpus(args.corpus) if args.corpus else None
    scores: list[float] = []

    for rp in args.results:
        result = _load_json(rp)
        g2 = g2_recall_precision(
            result, registry,
            recall_metric=args.recall_metric, embed_fn=embed_fn,
            tau=args.tau, tau_nc=args.tau_nc,
            corpus=corpus,
        )
        if g2.passed or g2.details.get("recall") is not None:
            scores.append(g2.details.get("recall", 0.0))

    if len(scores) < 2:
        print(
            f"ERROR: need >= 2 runs for aa_band; got {len(scores)}.  "
            "Make sure the registry is non-empty and the runs are valid.",
            file=sys.stderr,
        )
        return 1

    band = aa_band(scores)
    high_var = left_skew_flag(scores)
    print(f"A/A noise band (95th-pct pairwise delta): {band:.4f}")
    print(f"Scores across reruns: {[round(s, 4) for s in scores]}")
    if high_var:
        print("WARNING: HIGH_VARIANCE — min < median - 0.10.  Investigate before using this band.")
    return 0


# ── day-zero ──────────────────────────────────────────────────────────────────


def cmd_day_zero(args: argparse.Namespace) -> int:
    result = _load_json(args.result)
    registry = load_registry(args.registry)

    if not args.corpus:
        print(
            "ERROR: day-zero (a promotion decision) requires --corpus for evidence\n"
            "verification — a champion must not be minted on unverified evidence.\n"
            "  Supply the run's input bundle, e.g.  --corpus experiments/<corpus>/input.json",
            file=sys.stderr,
        )
        return 2
    corpus = load_corpus(args.corpus)

    if args.signoffs < 2:
        print(
            f"ERROR: Day-Zero requires 2 independent human sign-offs; got {args.signoffs}.",
            file=sys.stderr,
        )
        return 1

    gate_results = run_gates(
        result,
        registry,
        args.registry,
        is_day_zero=True,
        human_signed_off=True,
        signoff_count=args.signoffs,
        corpus=corpus,
    )

    config = _eval_config(args, registry, corpus)
    _write_eval_config(args.result, config)
    experiment_config = _read_experiment_config(args.result)
    v = get_verdict(gate_results)
    scorecard = render_scorecard(
        gate_results,
        corpus=registry.corpus,
        model_id=args.model_id or "unknown",
        run_id=args.run_id or "day-zero",
        is_self_graded=True,
        kappa_advisory=registry.is_kappa_advisory(),
        config=config,
        experiment_config=experiment_config,
    )
    print(scorecard)

    if v == "PROMOTE" and args.baseline:
        g2 = next((g for g in gate_results if g.gate == "G2"), None)
        g3 = next((g for g in gate_results if g.gate == "G3"), None)
        scores = {}
        if g2:
            scores["recall"] = g2.details.get("recall", 0.0)
        if g3:
            scores["grounding_pct"] = g3.details.get("grounding_pct", 0.0)

        champion = ChampionRecord(
            corpus=registry.corpus,
            run_id=args.run_id or "day-zero",
            model_id=args.model_id or "unknown",
            registry_sha256=registry.sha256(),
            scores=scores,
            is_day_zero=True,
            human_sign_offs=[f"signoff-{i + 1}" for i in range(args.signoffs)],
            config=config,
            corpus_sha256=corpus.sha256,
        )
        save_champion(
            args.baseline,
            champion,
            summary=f"Day-Zero champion for {registry.corpus}",
            date=args.date or "unknown",
        )
        print(f"\nDay-Zero champion saved to {args.baseline}")

    return 0 if v == "PROMOTE" else 1


# ── invalidate ────────────────────────────────────────────────────────────────


def cmd_invalidate(args: argparse.Namespace) -> int:
    invalidate_champion(args.baseline, reason=args.reason, date=args.date or "unknown")
    print(f"Champion invalidated in {args.baseline}.  Reason: {args.reason}")
    return 0


# ── parser ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flyeval",
        description="FlyRadar Lean Core eval: G1-G3 + G5 deterministic, G4 judge on by default",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--result", required=True, help="Path to DiscoveryResult JSON")
        p.add_argument("--registry", required=True, help="Path to lean-1 registry JSON")
        p.add_argument(
            "--corpus",
            help="Path to the run's input.json corpus bundle — enables deterministic "
            "evidence verification (required for day-zero; without it, gate runs "
            "carry an EVIDENCE UNVERIFIED disclosure)",
        )
        p.add_argument("--baseline", help="Path to baseline.json (per-corpus champion store)")
        p.add_argument("--model-id", default="unknown")
        p.add_argument("--run-id", default="run")
        p.add_argument("--date", default="", help="ISO date for promotion log")

    # gate
    p_gate = sub.add_parser("gate", help="Run the gates and print a scorecard")
    _add_common(p_gate)
    p_gate.add_argument("--recall-floor", type=float, default=0.70)
    p_gate.add_argument("--grounding-floor", type=float, default=0.90)
    p_gate.add_argument("--pii-list", nargs="*", default=[])
    p_gate.add_argument(
        "--embedder",
        default=os.environ.get("FLYEVAL_EMBEDDER"),
        help="opt-in embedder spec for the semantic recall path "
        '(e.g. "azure:text-embedding-3-small"); omit for pure-lexical recall. '
        "Env: FLYEVAL_EMBEDDER",
    )
    p_gate.add_argument(
        "--recall-metric",
        choices=["lexical", "semantic", "hybrid"],
        default=os.environ.get("FLYEVAL_RECALL_METRIC", "hybrid"),
        help="which recall metric GATES (default hybrid; hybrid/semantic require --embedder). "
        "Env: FLYEVAL_RECALL_METRIC",
    )
    p_gate.add_argument(
        "--tau",
        type=float,
        default=float(os.environ.get("FLYEVAL_TAU", "0.70")),
        help="cosine similarity threshold for the semantic recall path (real items). "
        "Env: FLYEVAL_TAU",
    )
    p_gate.add_argument(
        "--tau-nc",
        type=float,
        default=float(os.environ.get("FLYEVAL_TAU_NC", "0.85")),
        help="cosine similarity threshold for NC item detection (higher; no source anchor). "
        "Env: FLYEVAL_TAU_NC",
    )
    p_gate.add_argument("--human-signed-off", action="store_true")
    p_gate.add_argument("--signoffs", type=int, default=0)
    p_gate.add_argument(
        "--judge-model",
        default=os.environ.get("FLYEVAL_JUDGE_MODEL", "anthropic:claude-sonnet-4-6"),
        help="provider:model for the non-blocking G4 LLM-as-a-Judge (e.g. azure:gpt-4o). "
        "Runs by default; pass --no-judge to skip G4. Env: FLYEVAL_JUDGE_MODEL",
    )
    p_gate.add_argument(
        "--no-judge",
        action="store_true",
        help="skip the G4 LLM-as-a-Judge (it runs by default).",
    )
    p_gate.add_argument(
        "--judge-runs",
        type=int,
        default=int(os.environ.get("FLYEVAL_JUDGE_RUNS", "1")),
        help="G4 judge runs; the median of numeric scores is kept (odd recommended). "
        "Env: FLYEVAL_JUDGE_RUNS",
    )
    p_gate.add_argument(
        "--judge-concurrency",
        type=int,
        default=int(os.environ.get("FLYEVAL_JUDGE_CONCURRENCY", "1")),
        help="bounded fan-out for the per-item G4 [J] metrics (1 = sequential; "
        ">=2 runs each metric's chat calls across a thread pool, order preserved). "
        "Env: FLYEVAL_JUDGE_CONCURRENCY",
    )
    p_gate.add_argument(
        "--champion-result",
        help="Path to the champion's output.json for the G4 comparative-review metric",
    )
    p_gate.set_defaults(func=cmd_gate)

    # aa-band
    p_aa = sub.add_parser("aa-band", help="Compute A/A noise band from champion reruns")
    p_aa.add_argument(
        "--results",
        nargs="+",
        required=True,
        help="Paths to champion-rerun result JSON files (>= 2)",
    )
    p_aa.add_argument("--registry", required=True)
    p_aa.add_argument(
        "--recall-metric",
        choices=["lexical", "semantic", "hybrid"],
        default="hybrid",
        help="recall metric to use — must match the champion's metric (default hybrid; "
        "hybrid/semantic require --embedder)",
    )
    p_aa.add_argument(
        "--embedder",
        default=None,
        help="embedder spec for semantic/hybrid recall (e.g. ollama:bge-m3)",
    )
    p_aa.add_argument("--tau", type=float, default=0.70)
    p_aa.add_argument("--tau-nc", type=float, default=0.85)
    p_aa.add_argument(
        "--corpus",
        help="Path to input.json — must match the gate's corpus setting so the "
        "band is computed under the same evidence filtering as the champion",
    )
    p_aa.set_defaults(func=cmd_aa_band)

    # day-zero
    p_dz = sub.add_parser("day-zero", help="Promote the inaugural champion (Day-Zero protocol)")
    _add_common(p_dz)
    p_dz.add_argument(
        "--signoffs",
        type=int,
        default=0,
        help="Number of independent human sign-offs collected (need 2)",
    )
    p_dz.set_defaults(func=cmd_day_zero)

    # invalidate
    p_inv = sub.add_parser("invalidate", help="Invalidate the current champion")
    p_inv.add_argument("--baseline", required=True)
    p_inv.add_argument("--reason", required=True)
    p_inv.add_argument("--date", default="")
    p_inv.set_defaults(func=cmd_invalidate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
