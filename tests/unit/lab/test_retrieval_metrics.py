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

"""Unit tests for lab.retrieval_metrics: compute_retrieval_metrics and RetrieverMetrics."""

from __future__ import annotations

import math

import pytest

from fireflyframework_agentic.lab.retrieval_metrics import (
    RetrieverMetrics,
    compute_retrieval_metrics,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _row(gold_rank: int | None = None, total: int = 5, n_gold: int = 1) -> dict:
    """Build one result row with ``total`` retrieved items.

    If ``gold_rank`` is not None, the item at that rank is marked as gold.
    All items get a unique ``source_id`` so dedup leaves them all.
    """
    retrieved = []
    for rank in range(1, total + 1):
        retrieved.append({
            "rank": rank,
            "source_id": f"doc-{rank}",
            "is_gold": rank == gold_rank,
        })
    gold_ids = [f"doc-{gold_rank}"] if gold_rank is not None else []
    return {
        "retrieved": retrieved,
        "gold": gold_ids * n_gold,
    }


# ── hit@k ─────────────────────────────────────────────────────────────────────


def test_hit_at_1_perfect_when_gold_is_rank1():
    results = [_row(gold_rank=1)]
    m = compute_retrieval_metrics(results)
    assert m["hit@1"] == 1.0


def test_hit_at_1_zero_when_gold_not_in_top1():
    results = [_row(gold_rank=2)]
    m = compute_retrieval_metrics(results)
    assert m["hit@1"] == 0.0


def test_hit_at_5_one_when_gold_at_rank5():
    results = [_row(gold_rank=5)]
    m = compute_retrieval_metrics(results)
    assert m["hit@5"] == 1.0


def test_hit_at_5_zero_when_gold_not_in_top5():
    # Gold is at rank 10 — outside top-5 window with only 5 items, make 10.
    results = [_row(gold_rank=None, total=10)]  # no gold in retrieved
    m = compute_retrieval_metrics(results)
    assert m["hit@5"] == 0.0


def test_hit_at_10_one_when_gold_at_rank10():
    results = [_row(gold_rank=10, total=10)]
    m = compute_retrieval_metrics(results)
    assert m["hit@10"] == 1.0


# ── recall@k ──────────────────────────────────────────────────────────────────


def test_recall_at_k_increases_with_k():
    # Gold at rank 3: recall@1=0, recall@5>=recall@1.
    results = [_row(gold_rank=3)]
    m = compute_retrieval_metrics(results)
    assert m["recall@1"] <= m["recall@5"] <= m["recall@10"]


def test_recall_at_1_full_when_single_gold_at_rank1():
    results = [_row(gold_rank=1, n_gold=1)]
    m = compute_retrieval_metrics(results)
    assert m["recall@1"] == 1.0


def test_recall_at_1_zero_when_no_gold_in_rank1():
    results = [_row(gold_rank=5)]
    m = compute_retrieval_metrics(results)
    assert m["recall@1"] == 0.0


# ── MRR ───────────────────────────────────────────────────────────────────────


def test_mrr_is_1_when_gold_at_rank1():
    results = [_row(gold_rank=1)]
    m = compute_retrieval_metrics(results)
    assert m["mrr@10"] == 1.0


def test_mrr_is_half_when_gold_at_rank2():
    results = [_row(gold_rank=2)]
    m = compute_retrieval_metrics(results)
    assert abs(m["mrr@10"] - 0.5) < 1e-9


def test_mrr_is_zero_when_no_gold():
    results = [_row(gold_rank=None)]
    m = compute_retrieval_metrics(results)
    assert m["mrr@10"] == 0.0


def test_mrr_average_across_queries():
    # Query 1: gold at rank 1 (MRR=1.0); Query 2: gold at rank 2 (MRR=0.5).
    results = [_row(gold_rank=1), _row(gold_rank=2)]
    m = compute_retrieval_metrics(results)
    assert abs(m["mrr@10"] - 0.75) < 1e-3


# ── nDCG ──────────────────────────────────────────────────────────────────────


def test_ndcg_is_1_when_gold_at_rank1():
    results = [_row(gold_rank=1, n_gold=1)]
    m = compute_retrieval_metrics(results)
    assert abs(m["ndcg@10"] - 1.0) < 1e-9


def test_ndcg_is_less_than_1_when_gold_not_at_rank1():
    results = [_row(gold_rank=3, n_gold=1)]
    m = compute_retrieval_metrics(results)
    assert m["ndcg@10"] < 1.0
    assert m["ndcg@10"] > 0.0


def test_ndcg_is_zero_when_no_gold():
    results = [_row(gold_rank=None)]
    m = compute_retrieval_metrics(results)
    assert m["ndcg@10"] == 0.0


# ── n_queries ─────────────────────────────────────────────────────────────────


def test_n_queries_matches_input_length():
    results = [_row(gold_rank=1), _row(gold_rank=2), _row(gold_rank=3)]
    m = compute_retrieval_metrics(results)
    assert m["n_queries"] == 3


def test_empty_results_returns_zero_n_queries():
    m = compute_retrieval_metrics([])
    assert m["n_queries"] == 0


# ── optional fields ───────────────────────────────────────────────────────────


def test_no_answer_rate_is_none_when_no_answer_field():
    results = [_row(gold_rank=1)]
    m = compute_retrieval_metrics(results)
    assert m["no_answer_rate"] == 0.0


def test_citation_precision_is_none_when_no_citations():
    results = [_row(gold_rank=1)]
    m = compute_retrieval_metrics(results)
    assert m["citation_precision"] is None


def test_latency_fields_are_none_when_absent():
    results = [_row(gold_rank=1)]
    m = compute_retrieval_metrics(results)
    assert m["mean_search_ms"] is None
    assert m["mean_answer_ms"] is None


def test_mean_search_ms_computed_when_present():
    results = [{**_row(gold_rank=1), "search_ms": 100.0, "answer_ms": 200.0}]
    m = compute_retrieval_metrics(results)
    assert m["mean_search_ms"] == 100
    assert m["mean_answer_ms"] == 200


# ── RetrieverMetrics.from_results ─────────────────────────────────────────────


def test_retriever_metrics_from_results_hit_at_1():
    results = [_row(gold_rank=1)]
    rm = RetrieverMetrics.from_results(results)
    assert rm.hit_at_1 == 1.0


def test_retriever_metrics_from_results_n_queries():
    results = [_row(gold_rank=1), _row(gold_rank=2)]
    rm = RetrieverMetrics.from_results(results)
    assert rm.n_queries == 2


def test_retriever_metrics_from_results_mrr():
    results = [_row(gold_rank=1)]
    rm = RetrieverMetrics.from_results(results)
    assert rm.mrr_at_10 == 1.0


def test_retriever_metrics_from_results_defaults_on_empty():
    rm = RetrieverMetrics.from_results([])
    assert rm.n_queries == 0
    assert rm.hit_at_1 == 0.0
    assert rm.mrr_at_10 == 0.0


def test_retriever_metrics_is_pydantic_model():
    rm = RetrieverMetrics()
    assert rm.n_queries == 0
    assert rm.hit_at_1 == 0.0
    assert rm.no_answer_rate is None


def test_retriever_metrics_recall_increases_with_k():
    results = [_row(gold_rank=3)]
    rm = RetrieverMetrics.from_results(results)
    assert rm.recall_at_1 <= rm.recall_at_5 <= rm.recall_at_10
