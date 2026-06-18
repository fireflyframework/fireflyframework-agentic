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

"""FlyCanon evaluation example — RAG retrieval benchmark with champion/challenger tracking.

Demonstrates how to use ``fireflyframework_agentic.evaluation`` to replicate
the flycanon experiment evaluation workflow:

1. Load a results JSONL file produced by a flycanon retrieval pipeline.
2. Compute deterministic IR metrics (Recall@k, Precision@k, MRR, nDCG, MAP).
3. Compare against a saved baseline to detect regression.
4. Print a formatted metrics table.
5. Offer to promote the new run to champion when it beats the baseline.

The champion/challenger pattern mirrors the flycanon_experiments harness:
each run writes metrics to a file; ``approve`` promotes it by repointing
baseline.json.  Here we replicate that flow using the framework's
``compute_retrieval_metrics`` / ``RetrieverMetrics`` API directly.

Usage::

    # Score a results file (no baseline comparison)
    python examples/flycanon_eval_example.py --results-file results.jsonl

    # Compare against a saved baseline
    python examples/flycanon_eval_example.py \\
        --results-file results.jsonl \\
        --baseline baseline.json

    # Promote if better (write new champion to baseline.json)
    python examples/flycanon_eval_example.py \\
        --results-file results.jsonl \\
        --baseline baseline.json \\
        --promote-if-better

Exit codes: 0 = scored successfully, 1 = regression detected vs baseline.

Results JSONL format
--------------------
Each line is a JSON object representing one query's retrieval result::

    {
        "question": "What was Apple's revenue in Q4 2023?",
        "gold": ["AAPL_10K_2023", "AAPL_10Q_Q4_2023"],
        "retrieved": [
            {"rank": 1, "source_id": "AAPL_10K_2023",  "is_gold": true},
            {"rank": 2, "source_id": "MSFT_10K_2023",  "is_gold": false},
            {"rank": 3, "source_id": "AAPL_10Q_Q4_2023", "is_gold": true}
        ],
        "answer": "Apple's revenue in Q4 2023 was $89.5 billion.",
        "no_answer": false,
        "citations": [
            {"source_id": "AAPL_10K_2023", "is_gold": true}
        ],
        "search_ms": 142,
        "answer_ms": 2310
    }

The ``gold`` list contains the source IDs that are considered correct answers.
Each entry in ``retrieved`` must have a 1-based ``rank``, ``source_id`` (or
``identities`` list), and ``is_gold`` bool.

Baseline JSON format
--------------------
A flat JSON object with metric names as keys and float values::

    {
        "ndcg@10": 0.7234,
        "mrr@10": 0.6891,
        "recall@10": 0.8120,
        "hit@10": 0.9100,
        "map@10": 0.6543,
        "n_queries": 200
    }

This is the same format written by ``--promote-if-better``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fireflyframework_agentic.evaluation import RetrieverMetrics, compute_retrieval_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Metrics that form the primary quality signal for champion/challenger
# comparisons.  These are listed in priority order: nDCG@10 is the primary
# ranking metric; MRR@10 measures how quickly the first gold result appears;
# Recall@10 measures overall coverage; Hit@10 measures binary success rate;
# MAP@10 measures precision across the ranked list.
PRIMARY_METRICS = ["ndcg@10", "mrr@10", "recall@10", "hit@10", "map@10"]

# Regression threshold: a metric must drop by more than this fraction of its
# baseline value to be flagged as a regression (guards against noise).
REGRESSION_THRESHOLD = 0.01


def _load_jsonl(path: str) -> list[dict]:
    """Load a newline-delimited JSON file, one object per line."""
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _load_baseline(path: str) -> dict | None:
    """Load a baseline JSON file, returning None if it does not exist."""
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _save_baseline(path: str, metrics: dict) -> None:
    """Write a flat metrics dict to the baseline JSON file."""
    Path(path).write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _metrics_to_flat(m: RetrieverMetrics) -> dict:
    """Convert a RetrieverMetrics model to the flat dict stored in baseline.json."""
    return {
        "n_queries": m.n_queries,
        "hit@1": m.hit_at_1,
        "hit@5": m.hit_at_5,
        "hit@10": m.hit_at_10,
        "recall@1": m.recall_at_1,
        "recall@5": m.recall_at_5,
        "recall@10": m.recall_at_10,
        "precision@1": m.precision_at_1,
        "precision@5": m.precision_at_5,
        "precision@10": m.precision_at_10,
        "mrr@10": m.mrr_at_10,
        "map@10": m.map_at_10,
        "ndcg@10": m.ndcg_at_10,
        "no_answer_rate": m.no_answer_rate,
        "citation_precision": m.citation_precision,
        "mean_search_ms": m.mean_search_ms,
        "mean_answer_ms": m.mean_answer_ms,
    }


def _print_metrics_table(metrics: RetrieverMetrics, baseline: dict | None) -> None:
    """Print a formatted table comparing current metrics vs baseline."""
    flat = _metrics_to_flat(metrics)

    col_w = 22
    num_w = 10
    header = f"{'Metric':<{col_w}} {'Current':>{num_w}}"
    if baseline:
        header += f" {'Baseline':>{num_w}} {'Delta':>{num_w}}"
    print(header)
    print("-" * (col_w + num_w + (num_w * 2 + 2 if baseline else 0)))

    for key, value in flat.items():
        if value is None:
            continue
        # Format floats as 4 decimal places; ints as plain integers.
        if isinstance(value, float):
            cur_str = f"{value:.4f}"
        else:
            cur_str = str(value)

        row = f"{key:<{col_w}} {cur_str:>{num_w}}"
        if baseline and key in baseline and isinstance(value, float):
            base_val = baseline[key]
            delta = value - base_val
            delta_str = f"{delta:+.4f}"
            row += f" {base_val:>{num_w}.4f} {delta_str:>{num_w}}"
        print(row)

    print()


def _detect_regressions(flat: dict, baseline: dict) -> list[str]:
    """Return the names of primary metrics that regressed vs baseline.

    A regression is flagged when the new value drops by more than
    REGRESSION_THRESHOLD * baseline_value (relative threshold).  This
    guards against flagging noise as a regression.
    """
    regressions = []
    for key in PRIMARY_METRICS:
        new_val = flat.get(key)
        base_val = baseline.get(key)
        if new_val is None or base_val is None:
            continue
        if base_val > 0 and (base_val - new_val) / base_val > REGRESSION_THRESHOLD:
            regressions.append(key)
    return regressions


def _beats_baseline(flat: dict, baseline: dict) -> bool:
    """Return True if the new metrics are better than or equal to the baseline.

    'Better' means no primary metric has regressed beyond REGRESSION_THRESHOLD
    AND at least one primary metric has improved.
    """
    regressions = _detect_regressions(flat, baseline)
    if regressions:
        return False
    # Check for at least one improvement.
    for key in PRIMARY_METRICS:
        new_val = flat.get(key)
        base_val = baseline.get(key)
        if new_val is not None and base_val is not None and new_val > base_val:
            return True
    return False


# ---------------------------------------------------------------------------
# Main evaluation flow
# ---------------------------------------------------------------------------


def run_evaluation(args: argparse.Namespace) -> int:
    """Run retrieval metric scoring and optional champion/challenger comparison."""

    # ------------------------------------------------------------------
    # Step 1 — Load results from the JSONL file.
    #
    # Each line is one query's retrieval result.  The file is produced by
    # a flycanon pipeline run (runner.run_queries writes results.jsonl).
    # ------------------------------------------------------------------
    print(f"Loading results  : {args.results_file}")
    results = _load_jsonl(args.results_file)
    print(f"  {len(results)} query results loaded.")

    if not results:
        print("ERROR: results file is empty.", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Step 2 — Compute deterministic IR metrics.
    #
    # compute_retrieval_metrics() returns a flat dict of standard IR metrics.
    # RetrieverMetrics.from_results() wraps that into a typed Pydantic model
    # for convenient attribute access.
    #
    # Metrics are computed at cut-offs k ∈ {1, 5, 10} and include:
    #   hit@k       -- at least one gold doc in top-k (binary)
    #   recall@k    -- fraction of gold docs found in top-k
    #   precision@k -- fraction of top-k that are gold
    #   mrr@10      -- mean reciprocal rank of first gold hit
    #   map@10      -- mean average precision
    #   ndcg@10     -- normalised discounted cumulative gain
    # ------------------------------------------------------------------
    print("\nComputing retrieval metrics ...")
    metrics = RetrieverMetrics.from_results(results)

    print(f"  nDCG@10    : {metrics.ndcg_at_10:.4f}")
    print(f"  MRR@10     : {metrics.mrr_at_10:.4f}")
    print(f"  Recall@10  : {metrics.recall_at_10:.4f}")
    print(f"  Hit@10     : {metrics.hit_at_10:.4f}")
    print(f"  MAP@10     : {metrics.map_at_10:.4f}")

    # ------------------------------------------------------------------
    # Step 3 — Load the baseline (champion) for regression detection.
    # ------------------------------------------------------------------
    baseline = None
    if args.baseline:
        baseline = _load_baseline(args.baseline)
        if baseline:
            print(f"\nLoaded baseline  : {args.baseline}")
        else:
            print(f"\nNo baseline found at {args.baseline} — first run, no comparison.")

    # ------------------------------------------------------------------
    # Step 4 — Print the full metrics table.
    # ------------------------------------------------------------------
    print("\n" + "=" * 56)
    print("Retrieval Metrics")
    print("=" * 56)
    _print_metrics_table(metrics, baseline)

    # ------------------------------------------------------------------
    # Step 5 — Regression check.
    #
    # Compare against the baseline on primary metrics.  Regressions block
    # promotion (exit code 1) unless --promote-if-better is set and the
    # run actually improved overall.
    # ------------------------------------------------------------------
    flat = _metrics_to_flat(metrics)

    if baseline:
        regressions = _detect_regressions(flat, baseline)
        if regressions:
            print(f"REGRESSION detected on: {', '.join(regressions)}")
            print(f"  Threshold: {REGRESSION_THRESHOLD * 100:.0f}% relative drop on any primary metric.")
        else:
            better = _beats_baseline(flat, baseline)
            if better:
                print("Challenger BEATS baseline on at least one primary metric.")
            else:
                print("Challenger is on-par with baseline (no regression, no improvement).")

        if regressions and not args.promote_if_better:
            print("\nVerdict: HOLD — regression detected.  Tune the pipeline and re-run.")
            return 1

    # ------------------------------------------------------------------
    # Step 6 — Champion promotion.
    #
    # When --promote-if-better is set and the metrics beat (or equal) the
    # baseline, save the new metrics as the champion.  Future runs will
    # compare against this updated record.
    # ------------------------------------------------------------------
    if args.promote_if_better and args.baseline:
        if baseline is None or _beats_baseline(flat, baseline):
            _save_baseline(args.baseline, flat)
            print(f"\nChampion PROMOTED — metrics saved to {args.baseline}")
        else:
            print("\nNot promoted — challenger did not beat baseline on primary metrics.")

    print("\nVerdict: PROMOTE" if not (baseline and _detect_regressions(flat, baseline)) else "\nVerdict: HOLD")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flycanon_eval_example",
        description=(
            "FlyCanon RAG retrieval benchmark — computes IR metrics from a results JSONL "
            "and compares against a champion baseline."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--results-file",
        required=True,
        help="Path to results.jsonl produced by the flycanon pipeline.",
    )
    p.add_argument(
        "--baseline",
        default=None,
        help=(
            "Path to baseline.json (champion store).  When absent, scores are printed "
            "without comparison."
        ),
    )
    p.add_argument(
        "--promote-if-better",
        action="store_true",
        help=(
            "When set, write new metrics to baseline.json if the challenger beats the "
            "champion on primary metrics.  Has no effect when --baseline is omitted."
        ),
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run_evaluation(args))


if __name__ == "__main__":
    main()
