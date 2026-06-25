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

"""RAG retrieval evaluation example.

Compute deterministic IR metrics (Hit@k, Recall@k, Precision@k, MRR, MAP, nDCG)
from a JSONL results file produced by any retrieval pipeline.

Usage::

    python examples/rag_eval_example.py --results-file results.jsonl

Results JSONL format — one JSON object per line::

    {
        "question": "What was Apple's revenue in Q4 2023?",
        "gold": ["AAPL_10K_2023", "AAPL_10Q_Q4_2023"],
        "retrieved": [
            {"rank": 1, "source_id": "AAPL_10K_2023",  "is_gold": true},
            {"rank": 2, "source_id": "MSFT_10K_2023",  "is_gold": false},
            {"rank": 3, "source_id": "AAPL_10Q_Q4_2023", "is_gold": true}
        ],
        "answer": "Apple's revenue in Q4 2023 was $89.5 billion.",
        "citations": [{"source_id": "AAPL_10K_2023", "is_gold": true}],
        "search_ms": 142,
        "answer_ms": 2310
    }
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fireflyframework_agentic.evaluation import (
    citation_precision,
    hit_at_k,
    map_score,
    mean_latency_ms,
    mrr,
    ndcg,
    no_answer_rate,
    precision_at_k,
    recall_at_k,
)


def _load_jsonl(path: str) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute IR metrics from a retrieval results JSONL.")
    parser.add_argument("--results-file", required=True, help="Path to results.jsonl")
    parser.add_argument("--k", type=int, default=10, help="Cut-off rank (default: 10)")
    args = parser.parse_args()

    results = _load_jsonl(args.results_file)
    k = args.k

    metrics = {
        f"hit@{k}": hit_at_k(results, k),
        f"recall@{k}": recall_at_k(results, k),
        f"precision@{k}": precision_at_k(results, k),
        f"mrr@{k}": mrr(results, k),
        f"map@{k}": map_score(results, k),
        f"ndcg@{k}": ndcg(results, k),
        "no_answer_rate": no_answer_rate(results),
        "citation_precision": citation_precision(results),
        "mean_search_ms": mean_latency_ms(results, "search_ms"),
        "mean_answer_ms": mean_latency_ms(results, "answer_ms"),
    }

    print(f"\n{'Metric':<22} {'Value':>10}")
    print("-" * 33)
    for name, value in metrics.items():
        if value is not None:
            val_str = f"{value:.4f}" if isinstance(value, float) else str(value)
            print(f"{name:<22} {val_str:>10}")
    print(f"\n{len(results)} queries scored.")


if __name__ == "__main__":
    main()
