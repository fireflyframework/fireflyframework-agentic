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

"""Unit tests for evaluation.retrieval_metrics."""

from __future__ import annotations

from fireflyframework_agentic.evaluation.retrieval_metrics import (
    citation_precision,
    compute_retrieval_metrics,
    hit_at_k,
    map_score,
    mean_latency_ms,
    mrr,
    ndcg,
    no_answer_rate,
    precision_at_k,
    recall_at_k,
)


def _row(gold_rank: int | None = None, total: int = 5, n_gold: int = 1) -> dict:
    retrieved = []
    for rank in range(1, total + 1):
        retrieved.append({"rank": rank, "source_id": f"doc-{rank}", "is_gold": rank == gold_rank})
    gold_ids = [f"doc-{gold_rank}"] if gold_rank is not None else []
    return {"retrieved": retrieved, "gold": gold_ids * n_gold}


# ── hit_at_k ──────────────────────────────────────────────────────────────────


def test_hit_at_k_gold_at_rank1():
    assert hit_at_k([_row(gold_rank=1)], k=1) == 1.0


def test_hit_at_k_miss_at_rank1():
    assert hit_at_k([_row(gold_rank=2)], k=1) == 0.0


def test_hit_at_k_gold_at_rank5():
    assert hit_at_k([_row(gold_rank=5)], k=5) == 1.0


def test_hit_at_k_gold_at_rank10():
    assert hit_at_k([_row(gold_rank=10, total=10)], k=10) == 1.0


def test_hit_at_k_empty():
    assert hit_at_k([], k=5) == 0.0


# ── recall_at_k ───────────────────────────────────────────────────────────────


def test_recall_at_k_full_when_gold_at_rank1():
    assert recall_at_k([_row(gold_rank=1, n_gold=1)], k=1) == 1.0


def test_recall_at_k_zero_when_gold_outside_k():
    assert recall_at_k([_row(gold_rank=5)], k=1) == 0.0


def test_recall_at_k_increases_with_k():
    rows = [_row(gold_rank=3)]
    assert recall_at_k(rows, k=1) <= recall_at_k(rows, k=5) <= recall_at_k(rows, k=10)


# ── precision_at_k ────────────────────────────────────────────────────────────


def test_precision_at_k_gold_at_rank1():
    assert precision_at_k([_row(gold_rank=1)], k=1) == 1.0


def test_precision_at_k_decreases_when_k_larger():
    rows = [_row(gold_rank=1)]
    assert precision_at_k(rows, k=5) < precision_at_k(rows, k=1)


# ── mrr ───────────────────────────────────────────────────────────────────────


def test_mrr_gold_at_rank1():
    assert mrr([_row(gold_rank=1)]) == 1.0


def test_mrr_gold_at_rank2():
    assert abs(mrr([_row(gold_rank=2)]) - 0.5) < 1e-9


def test_mrr_no_gold():
    assert mrr([_row(gold_rank=None)]) == 0.0


def test_mrr_average_across_queries():
    rows = [_row(gold_rank=1), _row(gold_rank=2)]
    assert abs(mrr(rows) - 0.75) < 1e-3


# ── ndcg ──────────────────────────────────────────────────────────────────────


def test_ndcg_gold_at_rank1():
    assert abs(ndcg([_row(gold_rank=1, n_gold=1)]) - 1.0) < 1e-9


def test_ndcg_less_than_1_when_not_at_rank1():
    score = ndcg([_row(gold_rank=3, n_gold=1)])
    assert 0.0 < score < 1.0


def test_ndcg_zero_when_no_gold():
    assert ndcg([_row(gold_rank=None)]) == 0.0


# ── map_score ─────────────────────────────────────────────────────────────────


def test_map_score_perfect_when_gold_at_rank1():
    assert map_score([_row(gold_rank=1, n_gold=1)]) == 1.0


def test_map_score_zero_when_no_gold():
    assert map_score([_row(gold_rank=None)]) == 0.0


# ── no_answer_rate ────────────────────────────────────────────────────────────


def test_no_answer_rate_zero_when_answer_present():
    rows = [{**_row(gold_rank=1), "answer": "some answer"}]
    assert no_answer_rate(rows) == 0.0


def test_no_answer_rate_one_when_no_answer_field():
    assert no_answer_rate([_row(gold_rank=1)]) == 1.0


def test_no_answer_rate_none_when_empty():
    assert no_answer_rate([]) is None


# ── citation_precision ────────────────────────────────────────────────────────


def test_citation_precision_none_when_no_citations():
    assert citation_precision([_row(gold_rank=1)]) is None


def test_citation_precision_1_when_all_gold():
    rows = [{**_row(gold_rank=1), "citations": [{"is_gold": True}, {"is_gold": True}]}]
    assert citation_precision(rows) == 1.0


def test_citation_precision_half_when_half_gold():
    rows = [{**_row(gold_rank=1), "citations": [{"is_gold": True}, {"is_gold": False}]}]
    assert citation_precision(rows) == 0.5


# ── mean_latency_ms ───────────────────────────────────────────────────────────


def test_mean_latency_none_when_field_absent():
    assert mean_latency_ms([_row(gold_rank=1)], "search_ms") is None


def test_mean_latency_computed_when_present():
    rows = [{**_row(gold_rank=1), "search_ms": 100.0, "answer_ms": 200.0}]
    assert mean_latency_ms(rows, "search_ms") == 100
    assert mean_latency_ms(rows, "answer_ms") == 200


# ── compute_retrieval_metrics (aggregate) ─────────────────────────────────────


def test_compute_retrieval_metrics_n_queries():
    assert compute_retrieval_metrics([_row(1), _row(2), _row(3)])["n_queries"] == 3


def test_compute_retrieval_metrics_empty():
    m = compute_retrieval_metrics([])
    assert m["n_queries"] == 0
    assert m["hit@1"] == 0.0


def test_compute_retrieval_metrics_matches_individual_functions():
    rows = [_row(gold_rank=1), _row(gold_rank=2)]
    m = compute_retrieval_metrics(rows)
    assert m["hit@1"] == hit_at_k(rows, 1)
    assert m["recall@5"] == recall_at_k(rows, 5)
    assert m["mrr@10"] == mrr(rows)
    assert m["ndcg@10"] == ndcg(rows)
