# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Fixture loader and pre-computed ground-truth answers for the reasoning
end-to-end test suite.

The numbers below were computed from the committed CSV fixtures by a one-off
generator (not committed — anyone regenerating must read the spec and
confirm the formulas match current intent). If the CSVs change, regenerate
the dict and update both at once.

Per-question keys mirror the IDs used in the replay fixture filenames at
``tests/examples/corpus_search/replay/<key>.json``.
"""

from __future__ import annotations

from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent / "benchmark" / "corpus" / "reasoning"


GROUND_TRUTH: dict[str, dict] = {
    "q1_yoy_growth": {
        "tolerance_pct_points": 0.1,
        # Values in percentage points; e.g. 28.908 means +28.9 % YoY.
        # Computed as sum(2024 revenue, blanks=0) / sum(2023 revenue, blanks=0) - 1.
        "by_bu": {
            "Alpha": 28.908,
            "Beta": -19.4602,
            "Gamma": 22.9734,
        },
    },
    "q2_weighted_price": {
        "tolerance": 0.01,
        # sum(revenue_usd, blanks=0) / sum(units_sold) over all rows.
        "value": 154.5823,
    },
    "q3_mean_and_stdev_q4_2024_blanks_as_zero": {
        "tolerance": 0.01,
        # Per-region mean / sample stdev of revenue_usd for Q4 2024, blanks=0.
        "mean_by_region": {
            "NA": 31174.0267,
            "EU": 35302.5778,
        },
        "stdev_by_region": {
            "NA": 16982.8505,
            "EU": 24072.7053,
        },
    },
    "q4_headcount_cv_ranking": {
        # Coefficient of variation per BU over the 4 quarterly snapshots in
        # 2024, ranked most-stable (smallest CV) → least-stable.
        "ranking": ["Beta", "Gamma", "Alpha"],
        "cv_values": {
            "Alpha": 0.075676,
            "Beta": 0.042328,
            "Gamma": 0.054902,
        },
    },
    "q5_operating_efficiency_2024q3": {
        "tolerance": 0.5,
        # Operating Efficiency = sum(revenue_usd, blanks=0) for that BU's
        # 2024 Q3 rows, divided by the 2024-09-30 headcount snapshot.
        "by_bu": {
            "Alpha": 5322.8965,
            "Beta": 5972.8259,
            "Gamma": 3607.9665,
        },
    },
}


def fixture_path(name: str) -> Path:
    """Return the absolute path of a fixture file under FIXTURE_ROOT."""
    p = FIXTURE_ROOT / name
    if not p.exists():
        raise FileNotFoundError(p)
    return p
