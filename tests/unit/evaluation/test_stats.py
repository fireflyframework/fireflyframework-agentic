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

"""Unit tests for evaluation.stats: aa_band, aggregate_grounding, left_skew_flag."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.evaluation.stats import (
    aa_band,
    aggregate_grounding,
    left_skew_flag,
)


# ── aa_band ──────────────────────────────────────────────────────────────────


def test_aa_band_two_identical_scores():
    # Two identical scores produce zero pairwise delta.
    assert aa_band([0.80, 0.80]) == 0.0


def test_aa_band_two_different_scores():
    # Single delta = |0.90 - 0.80| = 0.10; 95th percentile of one value is that value.
    result = aa_band([0.80, 0.90])
    assert abs(result - 0.10) < 1e-9


def test_aa_band_three_scores_known_deltas():
    # Scores: 0.70, 0.80, 0.90
    # Pairwise deltas: |0.70-0.80|=0.10, |0.70-0.90|=0.20, |0.80-0.90|=0.10
    # Sorted: [0.10, 0.10, 0.20] → 95th pct index = int(3 * 95 / 100) = 2 → 0.20
    result = aa_band([0.70, 0.80, 0.90])
    assert abs(result - 0.20) < 1e-9


def test_aa_band_large_spread():
    # Max delta in [0.0, 1.0] is 1.0.
    result = aa_band([0.0, 1.0])
    assert abs(result - 1.0) < 1e-9


def test_aa_band_requires_at_least_two_scores():
    with pytest.raises(ValueError, match="aa_band requires >= 2 reruns"):
        aa_band([0.80])


def test_aa_band_empty_raises():
    with pytest.raises(ValueError, match="aa_band requires >= 2 reruns"):
        aa_band([])


def test_aa_band_custom_percentile():
    # 50th percentile of [0.10, 0.10, 0.20] at idx=1 → 0.10.
    result = aa_band([0.70, 0.80, 0.90], percentile=50)
    assert abs(result - 0.10) < 1e-9


def test_aa_band_returns_float():
    result = aa_band([0.80, 0.85, 0.90])
    assert isinstance(result, float)


# ── aggregate_grounding ───────────────────────────────────────────────────────


def test_aggregate_grounding_single_dict():
    g = {"support_pct": 90.0, "unsupported_ids": ["ev-1"]}
    result = aggregate_grounding([g])
    assert result["support_pct"] == 90.0
    assert result["unsupported_ids"] == ["ev-1"]
    assert result["_aggregate_runs"] == 1


def test_aggregate_grounding_mean_support_pct():
    dicts = [
        {"support_pct": 80.0, "unsupported_ids": []},
        {"support_pct": 100.0, "unsupported_ids": []},
    ]
    result = aggregate_grounding(dicts)
    assert result["support_pct"] == 90.0


def test_aggregate_grounding_union_of_unsupported_ids():
    dicts = [
        {"support_pct": 90.0, "unsupported_ids": ["ev-1", "ev-2"]},
        {"support_pct": 85.0, "unsupported_ids": ["ev-2", "ev-3"]},
    ]
    result = aggregate_grounding(dicts)
    assert set(result["unsupported_ids"]) == {"ev-1", "ev-2", "ev-3"}


def test_aggregate_grounding_union_sorted():
    dicts = [
        {"support_pct": 90.0, "unsupported_ids": ["ev-b"]},
        {"support_pct": 90.0, "unsupported_ids": ["ev-a"]},
    ]
    result = aggregate_grounding(dicts)
    assert result["unsupported_ids"] == ["ev-a", "ev-b"]


def test_aggregate_grounding_empty_input():
    result = aggregate_grounding([])
    assert result["support_pct"] == 0.0
    assert result["unsupported_ids"] == []


def test_aggregate_grounding_records_run_count():
    dicts = [
        {"support_pct": 80.0, "unsupported_ids": []},
        {"support_pct": 90.0, "unsupported_ids": []},
        {"support_pct": 100.0, "unsupported_ids": []},
    ]
    result = aggregate_grounding(dicts)
    assert result["_aggregate_runs"] == 3


def test_aggregate_grounding_per_run_pct_recorded():
    dicts = [
        {"support_pct": 80.0, "unsupported_ids": []},
        {"support_pct": 100.0, "unsupported_ids": []},
    ]
    result = aggregate_grounding(dicts)
    assert result["_support_pct_per_run"] == [80.0, 100.0]


def test_aggregate_grounding_missing_unsupported_ids_treated_as_empty():
    dicts = [
        {"support_pct": 90.0},  # no unsupported_ids key
        {"support_pct": 80.0, "unsupported_ids": ["ev-1"]},
    ]
    result = aggregate_grounding(dicts)
    assert result["unsupported_ids"] == ["ev-1"]


# ── left_skew_flag ────────────────────────────────────────────────────────────


def test_left_skew_flag_true_when_catastrophic_run():
    # median([0.80, 0.80, 0.80]) = 0.80; min = 0.60 < 0.80 - 0.10 = 0.70.
    assert left_skew_flag([0.60, 0.80, 0.80]) is True


def test_left_skew_flag_false_when_min_close_to_median():
    # median = 0.80; min = 0.75; 0.75 >= 0.80 - 0.10 = 0.70 → no flag.
    assert left_skew_flag([0.75, 0.80, 0.85]) is False


def test_left_skew_flag_false_when_all_equal():
    assert left_skew_flag([0.85, 0.85, 0.85]) is False


def test_left_skew_flag_boundary_just_above_threshold():
    # min = 0.71, median = 0.80; 0.71 >= 0.80 - 0.10 = 0.70 → no flag.
    assert left_skew_flag([0.71, 0.80, 0.80]) is False


def test_left_skew_flag_single_score_always_false():
    # A single score has no meaningful distribution; function returns False.
    assert left_skew_flag([0.50]) is False


def test_left_skew_flag_two_scores_with_large_gap():
    # median([0.50, 0.90]) = 0.70; min = 0.50 < 0.70 - 0.10 = 0.60.
    assert left_skew_flag([0.50, 0.90]) is True


def test_left_skew_flag_returns_bool():
    result = left_skew_flag([0.80, 0.85, 0.90])
    assert isinstance(result, bool)
