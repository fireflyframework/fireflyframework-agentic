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

"""Deterministic IR evaluation metrics for ranked retrieval results (no LLM, no network).

Industry-standard information-retrieval metrics computed over a ranked list of
retrieved chunks vs the gold set each result carries (``gold`` + per-hit
``is_gold``).  Metrics are reported at cut-offs k ∈ {1, 5, 10}:

* **Hit@k** -- at least one gold document appears in the top-k results.
* **Recall@k** -- fraction of gold documents found in top-k.
* **Precision@k** -- fraction of top-k results that are gold.
* **MRR@10** -- mean reciprocal rank of the first gold hit (up to k=10).
* **MAP@10** -- mean average precision (up to k=10).
* **nDCG@10** -- normalised discounted cumulative gain (up to k=10).

Optional fields (populated when the raw result rows contain them):

* ``no_answer_rate`` -- fraction of rows where the model produced no answer.
* ``citation_precision`` -- precision of in-answer citations vs gold set.
* ``mean_search_ms`` / ``mean_answer_ms`` -- mean retrieval and generation latencies.

Ported from ``flycanon_experiments/scripts/deterministic_eval.py``.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

KS = (1, 5, 10)


def _dedup(retrieved: list[dict]) -> list[dict]:
    """Return one entry per source, first chunk wins, preserving rank order.

    flycanon splits each ingested document into many chunks; a single gold
    filing can therefore appear multiple times in the ranked list.  Without
    deduplication nDCG/MAP/Recall count every chunk separately, inflating
    scores past 1.0 when a good embedding model retrieves several chunks from
    the same filing.  Taking only the first (highest-ranked) chunk per
    source_id makes the list item-unique, matching the recommenders-library
    contract that all IR formulae assume.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for r in sorted(retrieved, key=lambda x: x["rank"]):
        key = r.get("source_id") or "|".join(r.get("identities", []))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _ndcg(retrieved: list[dict], n_gold: int, k: int = 10) -> float:
    """Return nDCG@k for a single query."""
    dcg = sum(
        1.0 / math.log2(r["rank"] + 1)
        for r in retrieved
        if r.get("is_gold") and r["rank"] <= k
    )
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(n_gold, k)))
    return dcg / ideal if ideal else 0.0


def _ap(retrieved: list[dict], n_gold: int, k: int = 10) -> float:
    """Return average precision@k for a single query."""
    hits, precisions = 0, []
    for r in sorted(retrieved, key=lambda x: x["rank"]):
        if r["rank"] > k:
            break
        if r.get("is_gold"):
            hits += 1
            precisions.append(hits / r["rank"])
    return sum(precisions) / min(n_gold, k) if n_gold else 0.0


def compute_retrieval_metrics(results: list[dict]) -> dict:
    """Compute deterministic IR metrics over a list of retrieval result rows.

    Each element of *results* must be a dict with at least:

    * ``retrieved`` -- list of dicts with ``rank`` (int, 1-based), ``source_id``
      (str) or ``identities`` (list[str]), and ``is_gold`` (bool).
    * ``gold`` -- list of gold source identifiers (used to compute ``n_gold``).

    Optional keys per row:

    * ``no_answer`` (bool) / ``answer`` (str) -- used for ``no_answer_rate``.
    * ``citations`` (list[dict]) -- each with ``is_gold`` (bool) for citation precision.
    * ``search_ms`` (float) / ``answer_ms`` (float) -- latency in milliseconds.

    Returns a flat dict with keys: ``n_queries``, ``hit@1``, ``hit@5``,
    ``hit@10``, ``recall@1``, ``recall@5``, ``recall@10``, ``precision@1``,
    ``precision@5``, ``precision@10``, ``mrr@10``, ``map@10``, ``ndcg@10``,
    ``no_answer_rate``, ``citation_precision``, ``mean_search_ms``,
    ``mean_answer_ms``.
    """
    n = len(results)
    agg = {f"{m}@{k}": 0.0 for k in KS for m in ("hit", "recall", "precision")}
    agg.update({"mrr@10": 0.0, "map@10": 0.0, "ndcg@10": 0.0})
    no_answer = 0
    cite_num = cite_den = 0.0
    search_ms: list[float] = []
    answer_ms: list[float] = []

    for row in results:
        retrieved = _dedup(row["retrieved"])
        n_gold = max(len(set(row["gold"])), 1)
        gold_ranks = [r["rank"] for r in retrieved if r.get("is_gold")]
        for k in KS:
            in_k = [g for g in gold_ranks if g <= k]
            agg[f"hit@{k}"] += 1.0 if in_k else 0.0
            agg[f"recall@{k}"] += len(in_k) / n_gold
            agg[f"precision@{k}"] += len(in_k) / k
        agg["mrr@10"] += (1.0 / min(gold_ranks)) if gold_ranks else 0.0
        agg["map@10"] += _ap(retrieved, n_gold)
        agg["ndcg@10"] += _ndcg(retrieved, n_gold)

        if row.get("no_answer") or not row.get("answer", "").strip():
            no_answer += 1
        cites = row.get("citations", [])
        if cites:
            cite_num += sum(1 for c in cites if c.get("is_gold"))
            cite_den += len(cites)
        if row.get("search_ms") is not None:
            search_ms.append(row["search_ms"])
        if row.get("answer_ms") is not None:
            answer_ms.append(row["answer_ms"])

    out = {k: round(v / n, 4) for k, v in agg.items()} if n else {}
    out["n_queries"] = n
    out["no_answer_rate"] = round(no_answer / n, 4) if n else None
    out["citation_precision"] = round(cite_num / cite_den, 4) if cite_den else None
    out["mean_search_ms"] = round(sum(search_ms) / len(search_ms)) if search_ms else None
    out["mean_answer_ms"] = round(sum(answer_ms) / len(answer_ms)) if answer_ms else None
    return out


class RetrieverMetrics(BaseModel):
    """Structured IR metrics for a retrieval evaluation run.

    Fields mirror the flat dict returned by :func:`compute_retrieval_metrics`.
    Optional fields are ``None`` when the raw result rows lack the required data
    (e.g. no latency timestamps, no citations).
    """

    n_queries: int = 0
    hit_at_1: float = 0.0
    hit_at_5: float = 0.0
    hit_at_10: float = 0.0
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    precision_at_1: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    mrr_at_10: float = 0.0
    map_at_10: float = 0.0
    ndcg_at_10: float = 0.0
    no_answer_rate: float | None = None
    citation_precision: float | None = None
    mean_search_ms: float | None = None
    mean_answer_ms: float | None = None

    @classmethod
    def from_results(cls, results: list[dict]) -> "RetrieverMetrics":
        """Compute metrics from raw retrieval result rows and return a model instance."""
        m = compute_retrieval_metrics(results)
        return cls(
            n_queries=m.get("n_queries", 0),
            hit_at_1=m.get("hit@1", 0.0),
            hit_at_5=m.get("hit@5", 0.0),
            hit_at_10=m.get("hit@10", 0.0),
            recall_at_1=m.get("recall@1", 0.0),
            recall_at_5=m.get("recall@5", 0.0),
            recall_at_10=m.get("recall@10", 0.0),
            precision_at_1=m.get("precision@1", 0.0),
            precision_at_5=m.get("precision@5", 0.0),
            precision_at_10=m.get("precision@10", 0.0),
            mrr_at_10=m.get("mrr@10", 0.0),
            map_at_10=m.get("map@10", 0.0),
            ndcg_at_10=m.get("ndcg@10", 0.0),
            no_answer_rate=m.get("no_answer_rate"),
            citation_precision=m.get("citation_precision"),
            mean_search_ms=m.get("mean_search_ms"),
            mean_answer_ms=m.get("mean_answer_ms"),
        )
