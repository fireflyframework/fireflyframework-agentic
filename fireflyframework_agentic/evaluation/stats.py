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

"""Statistics helpers: A/A noise band + fixed aggregate_grounding.

The A/A band replaces McNemar, Wilcoxon, BCa bootstrap, Cliff's delta, Holm
correction, and MCID power analysis.  Four self-authored corpora with ~30-70
non-independent items each cannot power those tests; gating on unpowered tests
is false precision.  See EVALUATION_FRAMEWORK.md (regression statistics).

This module also provides the fixed aggregate_grounding() that closes a prior
aggregation bug where the previous runner inherited run 0's grounding report
unchanged instead of merging across all runs.
"""
from __future__ import annotations

import statistics
from typing import Sequence


def aa_band(scores: Sequence[float], *, percentile: int = 95) -> float:
    """95th-percentile pairwise delta from champion reruns — the noise floor.

    Rerun the champion ~10 times; the 95th-percentile of all pairwise absolute
    differences is the A/A noise floor.  A candidate must beat the champion by
    more than this number on EVERY seed to count as a real improvement.

    This single number replaces MCID, power analysis, McNemar, Wilcoxon,
    bootstrap CIs, and Holm correction.  See EVALUATION_FRAMEWORK.md (the A/A noise band).

    Args:
        scores: Per-run primary metric scores from champion reruns (>= 2 required).
        percentile: Which percentile (default 95).

    Returns:
        Noise floor as a float in the same units as the input scores.
    """
    scores = list(scores)
    if len(scores) < 2:
        raise ValueError(f"aa_band requires >= 2 reruns; got {len(scores)}")
    deltas = [
        abs(x - y)
        for i, x in enumerate(scores)
        for y in scores[i + 1:]
    ]
    sorted_deltas = sorted(deltas)
    # Index for the requested percentile; clamp to valid range
    idx = max(0, min(len(sorted_deltas) - 1, int(len(sorted_deltas) * percentile / 100)))
    return sorted_deltas[idx]


def aggregate_grounding(grounding_dicts: list[dict]) -> dict:
    """Merge per-run grounding reports into a conservative aggregate.

    Fixes a prior aggregation bug where the previous runner inherited run 0's grounding
    report unchanged.  Correct behaviour:
    - support_pct: mean across runs
    - unsupported_ids: UNION across all runs (anything flagged in any run stays flagged)

    Args:
        grounding_dicts: List of grounding report dicts, one per evaluation run.
            Each must have 'support_pct' (float 0-100) and optionally
            'unsupported_ids' (list[str]).

    Returns:
        Merged grounding dict.
    """
    if not grounding_dicts:
        return {"support_pct": 0.0, "unsupported_ids": []}

    support_pcts = [float(g.get("support_pct", 0.0)) for g in grounding_dicts]
    mean_pct = statistics.mean(support_pcts)

    unsupported: set[str] = set()
    for g in grounding_dicts:
        unsupported.update(g.get("unsupported_ids", []))

    first = grounding_dicts[0]
    return {
        **first,
        "support_pct": round(mean_pct, 2),
        "unsupported_ids": sorted(unsupported),
        "_aggregate_runs": len(grounding_dicts),
        "_support_pct_per_run": [round(p, 2) for p in support_pcts],
    }


def left_skew_flag(scores: Sequence[float]) -> bool:
    """True if min < median - 0.10 (HIGH_VARIANCE sentinel).

    A single catastrophic run cannot hide inside a decent mean.
    True => HIGH_VARIANCE; block the run until investigated.
    See EVALUATION_FRAMEWORK.md (anti-flakiness).
    """
    scores = list(scores)
    if len(scores) < 2:
        return False
    med = statistics.median(scores)
    return min(scores) < med - 0.10
