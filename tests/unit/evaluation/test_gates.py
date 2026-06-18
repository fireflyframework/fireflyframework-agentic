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

"""Unit tests for evaluation.gates: GateResult, verdict, render_scorecard, g5_no_regression."""

from __future__ import annotations

from fireflyframework_agentic.evaluation.gates import (
    GateResult,
    Verdict,
    g5_no_regression,
    render_scorecard,
)
from fireflyframework_agentic.evaluation.scorecard import verdict


# ── GateResult ────────────────────────────────────────────────────────────────


def test_gate_result_str_pass():
    gr = GateResult(gate="G1", passed=True)
    assert str(gr) == "[G1] PASS"


def test_gate_result_str_flag():
    gr = GateResult(gate="G2", passed=False, reason_code="RECALL_BELOW_FLOOR")
    assert str(gr) == "[G2] FLAG:RECALL_BELOW_FLOOR"


def test_gate_result_flag_without_reason_code():
    gr = GateResult(gate="G3", passed=False, reason_code="")
    assert str(gr) == "[G3] FLAG:"


def test_gate_result_passed_true():
    gr = GateResult(gate="G5", passed=True, details={"note": "ok"})
    assert gr.passed is True
    assert gr.details["note"] == "ok"


def test_gate_result_default_details_is_empty_dict():
    gr = GateResult(gate="G1", passed=True)
    assert gr.details == {}


# ── verdict ───────────────────────────────────────────────────────────────────


def test_verdict_promote_when_all_pass_and_g5_present():
    gates = [
        GateResult(gate="G1", passed=True),
        GateResult(gate="G2", passed=True),
        GateResult(gate="G3", passed=True),
        GateResult(gate="G5", passed=True),
    ]
    assert verdict(gates) == "PROMOTE"


def test_verdict_hold_when_any_gate_fails():
    gates = [
        GateResult(gate="G1", passed=True),
        GateResult(gate="G2", passed=False, reason_code="RECALL_BELOW_FLOOR"),
        GateResult(gate="G3", passed=True),
        GateResult(gate="G5", passed=True),
    ]
    assert verdict(gates) == "HOLD"


def test_verdict_hold_when_g5_missing():
    # All G1/G2/G3 pass but G5 is absent — no promotion without sign-off.
    gates = [
        GateResult(gate="G1", passed=True),
        GateResult(gate="G2", passed=True),
        GateResult(gate="G3", passed=True),
    ]
    assert verdict(gates) == "HOLD"


def test_verdict_hold_on_empty_list():
    assert verdict([]) == "HOLD"


def test_verdict_hold_when_g5_fails():
    gates = [
        GateResult(gate="G1", passed=True),
        GateResult(gate="G2", passed=True),
        GateResult(gate="G3", passed=True),
        GateResult(gate="G5", passed=False, reason_code="HOLD"),
    ]
    assert verdict(gates) == "HOLD"


# ── render_scorecard (from gates module) ──────────────────────────────────────


def test_render_scorecard_contains_verdict_line():
    gates = [
        GateResult(gate="G1", passed=True),
        GateResult(gate="G2", passed=True),
        GateResult(gate="G3", passed=True),
        GateResult(gate="G5", passed=True),
    ]
    output = render_scorecard(gates)
    assert "VERDICT: PROMOTE" in output


def test_render_scorecard_hold_when_flag():
    gates = [
        GateResult(gate="G1", passed=False, reason_code="SCHEMA_INVALID"),
        GateResult(gate="G2", passed=True),
        GateResult(gate="G3", passed=True),
        GateResult(gate="G5", passed=True),
    ]
    output = render_scorecard(gates)
    assert "VERDICT: HOLD" in output


def test_render_scorecard_includes_all_gate_lines():
    gates = [
        GateResult(gate="G1", passed=True),
        GateResult(gate="G2", passed=True),
        GateResult(gate="G3", passed=True),
        GateResult(gate="G5", passed=True),
    ]
    output = render_scorecard(gates)
    for gate_label in ("[G1]", "[G2]", "[G3]", "[G5]"):
        assert gate_label in output


# ── g5_no_regression ──────────────────────────────────────────────────────────


def test_g5_day_zero_insufficient_signoffs():
    result = g5_no_regression(
        candidate_scores={"recall": 0.85},
        champion_scores=None,
        aa_noise=None,
        is_day_zero=True,
        human_signed_off=False,
        signoff_count=1,
    )
    assert result.passed is False
    assert result.reason_code == "HOLD"


def test_g5_day_zero_sufficient_signoffs():
    result = g5_no_regression(
        candidate_scores={"recall": 0.85},
        champion_scores=None,
        aa_noise=None,
        is_day_zero=True,
        human_signed_off=False,
        signoff_count=2,
    )
    assert result.passed is True
    assert result.details["day_zero"] is True


def test_g5_hold_when_no_human_signoff():
    result = g5_no_regression(
        candidate_scores={"recall": 0.90},
        champion_scores={"recall": 0.80},
        aa_noise={"recall": 0.02},
        human_signed_off=False,
    )
    assert result.passed is False
    assert result.reason_code == "HOLD"


def test_g5_hold_when_regression_beyond_band():
    # Candidate recall 0.75 vs champion 0.80; delta=-0.05 < -band=-0.02.
    result = g5_no_regression(
        candidate_scores={"recall": 0.75},
        champion_scores={"recall": 0.80},
        aa_noise={"recall": 0.02},
        human_signed_off=True,
    )
    assert result.passed is False
    assert result.reason_code == "HOLD"
    assert any("recall" in r for r in result.details["regressions"])


def test_g5_promote_when_candidate_beats_champion():
    result = g5_no_regression(
        candidate_scores={"recall": 0.90},
        champion_scores={"recall": 0.80},
        aa_noise={"recall": 0.02},
        human_signed_off=True,
    )
    assert result.passed is True
    assert result.details["improvements"]


def test_g5_promote_when_within_noise_band():
    # delta = 0.01 — positive but within band of 0.02; counts as no regression, no improvement.
    result = g5_no_regression(
        candidate_scores={"recall": 0.81},
        champion_scores={"recall": 0.80},
        aa_noise={"recall": 0.02},
        human_signed_off=True,
    )
    assert result.passed is True
    assert result.details["improvements"] == []


def test_g5_verdict_constants():
    assert Verdict.PROMOTE == "PROMOTE"
    assert Verdict.HOLD == "HOLD"
