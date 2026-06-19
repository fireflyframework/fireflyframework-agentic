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

Each metric is a plain function that takes a list of result rows and returns a
float — the same design as scikit-learn or MS MARCO evaluation scripts.

Result row schema (dict)::

    {
        "retrieved": [{"rank": int, "source_id": str, "is_gold": bool}, ...],
        "gold": [str, ...],          # gold source identifiers
        # optional:
        "no_answer": bool,           # model refused / produced no answer
        "answer": str,               # used for no_answer detection when no_answer absent
        "citations": [{"is_gold": bool}, ...],
        "search_ms": float,
        "answer_ms": float,
    }

Individual metrics::

    hit_at_k(results, k)        -> float
    recall_at_k(results, k)     -> float
    precision_at_k(results, k)  -> float
    mrr(results, k=10)          -> float
    map_score(results, k=10)    -> float
    ndcg(results, k=10)         -> float
    no_answer_rate(results)     -> float | None
    citation_precision(results) -> float | None
    mean_latency_ms(results, field) -> float | None
"""

from __future__ import annotations

import math

def _dedup(retrieved: list[dict]) -> list[dict]:
    """Return one entry per source, first chunk wins, preserving rank order."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in sorted(retrieved, key=lambda x: x["rank"]):
        key = r.get("source_id") or "|".join(r.get("identities", []))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _ndcg_single(retrieved: list[dict], n_gold: int, k: int = 10) -> float:
    dcg = sum(1.0 / math.log2(r["rank"] + 1) for r in retrieved if r.get("is_gold") and r["rank"] <= k)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(n_gold, k)))
    return dcg / ideal if ideal else 0.0


def _ap_single(retrieved: list[dict], n_gold: int, k: int = 10) -> float:
    hits, precisions = 0, []
    for r in sorted(retrieved, key=lambda x: x["rank"]):
        if r["rank"] > k:
            break
        if r.get("is_gold"):
            hits += 1
            precisions.append(hits / r["rank"])
    return sum(precisions) / min(n_gold, k) if n_gold else 0.0


def hit_at_k(results: list[dict], k: int) -> float:
    """Fraction of queries where at least one gold document appears in top-k."""
    if not results:
        return 0.0
    hits = 0
    for row in results:
        retrieved = _dedup(row["retrieved"])
        gold_ranks = [r["rank"] for r in retrieved if r.get("is_gold")]
        if any(g <= k for g in gold_ranks):
            hits += 1
    return round(hits / len(results), 4)


def recall_at_k(results: list[dict], k: int) -> float:
    """Mean fraction of gold documents found in top-k."""
    if not results:
        return 0.0
    total = 0.0
    for row in results:
        retrieved = _dedup(row["retrieved"])
        n_gold = max(len(set(row["gold"])), 1)
        gold_ranks = [r["rank"] for r in retrieved if r.get("is_gold")]
        total += len([g for g in gold_ranks if g <= k]) / n_gold
    return round(total / len(results), 4)


def precision_at_k(results: list[dict], k: int) -> float:
    """Mean fraction of top-k results that are gold."""
    if not results:
        return 0.0
    total = 0.0
    for row in results:
        retrieved = _dedup(row["retrieved"])
        gold_ranks = [r["rank"] for r in retrieved if r.get("is_gold")]
        total += len([g for g in gold_ranks if g <= k]) / k
    return round(total / len(results), 4)


def mrr(results: list[dict], k: int = 10) -> float:
    """Mean reciprocal rank of the first gold hit (up to k)."""
    if not results:
        return 0.0
    total = 0.0
    for row in results:
        retrieved = _dedup(row["retrieved"])
        gold_ranks = sorted(r["rank"] for r in retrieved if r.get("is_gold") and r["rank"] <= k)
        total += 1.0 / gold_ranks[0] if gold_ranks else 0.0
    return round(total / len(results), 4)


def map_score(results: list[dict], k: int = 10) -> float:
    """Mean average precision at k."""
    if not results:
        return 0.0
    total = 0.0
    for row in results:
        retrieved = _dedup(row["retrieved"])
        n_gold = max(len(set(row["gold"])), 1)
        total += _ap_single(retrieved, n_gold, k)
    return round(total / len(results), 4)


def ndcg(results: list[dict], k: int = 10) -> float:
    """Mean normalised discounted cumulative gain at k."""
    if not results:
        return 0.0
    total = 0.0
    for row in results:
        retrieved = _dedup(row["retrieved"])
        n_gold = max(len(set(row["gold"])), 1)
        total += _ndcg_single(retrieved, n_gold, k)
    return round(total / len(results), 4)


def no_answer_rate(results: list[dict]) -> float | None:
    """Fraction of queries where the model produced no answer. None if no results."""
    if not results:
        return None
    count = sum(
        1 for row in results if row.get("no_answer") or not row.get("answer", "").strip()
    )
    return round(count / len(results), 4)


def citation_precision(results: list[dict]) -> float | None:
    """Precision of in-answer citations vs gold set. None if no citations present."""
    num = den = 0.0
    for row in results:
        cites = row.get("citations", [])
        if cites:
            num += sum(1 for c in cites if c.get("is_gold"))
            den += len(cites)
    return round(num / den, 4) if den else None


def mean_latency_ms(results: list[dict], field: str) -> float | None:
    """Mean latency in ms for the given field (``search_ms`` or ``answer_ms``). None if absent."""
    values = [row[field] for row in results if row.get(field) is not None]
    return round(sum(values) / len(values)) if values else None


