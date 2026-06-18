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

"""Unit tests for evaluation.champion: ChampionRecord, load/save/invalidate_champion, input_hash."""

from __future__ import annotations

import json

import pytest

from fireflyframework_agentic.evaluation.champion import (
    ChampionRecord,
    input_hash,
    invalidate_champion,
    load_champion,
    save_champion,
)


def _make_champion(**overrides) -> ChampionRecord:
    defaults = dict(
        corpus="test-corpus",
        run_id="run-2026-01",
        model_id="claude-sonnet-4-5",
        registry_sha256="abc123",
        scores={"recall": 0.85, "grounding_pct": 0.92},
        aa_noise={"recall": 0.02},
        is_day_zero=False,
        human_sign_offs=["reviewer-1"],
    )
    defaults.update(overrides)
    return ChampionRecord(**defaults)


# ── load_champion ─────────────────────────────────────────────────────────────


def test_load_champion_nonexistent_file_returns_none(tmp_path):
    result = load_champion(tmp_path / "baseline.json")
    assert result is None


def test_load_champion_file_with_null_champion_returns_none(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"champion": None, "promotion_log": []}), encoding="utf-8")
    assert load_champion(baseline) is None


# ── save_champion / load_champion round-trip ──────────────────────────────────


def test_save_then_load_round_trips_all_fields(tmp_path):
    baseline = tmp_path / "baseline.json"
    champ = _make_champion()
    save_champion(baseline, champ, summary="initial champion", date="2026-01-01")

    loaded = load_champion(baseline)
    assert loaded is not None
    assert loaded.corpus == champ.corpus
    assert loaded.run_id == champ.run_id
    assert loaded.model_id == champ.model_id
    assert loaded.registry_sha256 == champ.registry_sha256
    assert loaded.scores == champ.scores
    assert loaded.aa_noise == champ.aa_noise
    assert loaded.is_day_zero == champ.is_day_zero
    assert loaded.human_sign_offs == champ.human_sign_offs


def test_save_champion_appends_promotion_log_entry(tmp_path):
    baseline = tmp_path / "baseline.json"
    champ = _make_champion()
    save_champion(baseline, champ, summary="first", date="2026-01-01")

    champ2 = _make_champion(run_id="run-2026-02", scores={"recall": 0.90})
    save_champion(baseline, champ2, summary="second", date="2026-02-01")

    raw = json.loads(baseline.read_text(encoding="utf-8"))
    log = raw["promotion_log"]
    assert len(log) == 2
    assert log[0]["to"] == "run-2026-01"
    assert log[1]["to"] == "run-2026-02"
    assert log[1]["from"] == "run-2026-01"


def test_save_champion_creates_file_when_missing(tmp_path):
    baseline = tmp_path / "baseline.json"
    assert not baseline.exists()
    save_champion(baseline, _make_champion())
    assert baseline.exists()


def test_save_champion_day_zero_flag_preserved(tmp_path):
    baseline = tmp_path / "baseline.json"
    champ = _make_champion(is_day_zero=True)
    save_champion(baseline, champ)
    loaded = load_champion(baseline)
    assert loaded.is_day_zero is True


def test_save_champion_label_is_day_zero_when_flag_set(tmp_path):
    baseline = tmp_path / "baseline.json"
    champ = _make_champion(is_day_zero=True)
    save_champion(baseline, champ)
    raw = json.loads(baseline.read_text(encoding="utf-8"))
    assert raw["promotion_log"][0]["label"] == "day-zero"


def test_save_champion_label_is_promotion_when_flag_not_set(tmp_path):
    baseline = tmp_path / "baseline.json"
    save_champion(baseline, _make_champion(is_day_zero=False))
    raw = json.loads(baseline.read_text(encoding="utf-8"))
    assert raw["promotion_log"][0]["label"] == "promotion"


# ── invalidate_champion ───────────────────────────────────────────────────────


def test_invalidate_champion_sets_champion_to_null(tmp_path):
    baseline = tmp_path / "baseline.json"
    save_champion(baseline, _make_champion())
    invalidate_champion(baseline, reason="EMPTY_MUST_FIND fake champion", date="2026-03-01")

    loaded = load_champion(baseline)
    assert loaded is None

    raw = json.loads(baseline.read_text(encoding="utf-8"))
    assert raw["champion"] is None


def test_invalidate_champion_appends_invalidation_log(tmp_path):
    baseline = tmp_path / "baseline.json"
    save_champion(baseline, _make_champion(), date="2026-01-01")
    invalidate_champion(baseline, reason="fake champion", date="2026-03-01")

    raw = json.loads(baseline.read_text(encoding="utf-8"))
    log = raw["promotion_log"]
    assert log[-1]["label"] == "INVALIDATED"
    assert "fake champion" in log[-1]["summary"]
    assert log[-1]["to"] is None


def test_invalidate_champion_noop_when_file_missing(tmp_path):
    # Should not raise when file does not exist.
    invalidate_champion(tmp_path / "no-file.json", reason="test")


# ── ChampionRecord helpers ────────────────────────────────────────────────────


def test_primary_metric_returns_first_key():
    champ = _make_champion(scores={"recall": 0.85, "grounding_pct": 0.92})
    assert champ.primary_metric() == "recall"


def test_primary_score_returns_first_value():
    champ = _make_champion(scores={"recall": 0.85, "grounding_pct": 0.92})
    assert champ.primary_score() == 0.85


def test_primary_metric_empty_scores():
    champ = _make_champion(scores={})
    assert champ.primary_metric() == ""
    assert champ.primary_score() == 0.0


# ── input_hash ────────────────────────────────────────────────────────────────


def test_input_hash_is_16_chars():
    result = input_hash({"key": "value"})
    assert len(result) == 16


def test_input_hash_is_deterministic():
    data = {"process_graph": {"processes": []}, "findings": []}
    h1 = input_hash(data)
    h2 = input_hash(data)
    assert h1 == h2


def test_input_hash_differs_for_different_inputs():
    assert input_hash({"a": 1}) != input_hash({"a": 2})


def test_input_hash_key_order_independent():
    # sort_keys=True in input_hash should make {"a":1, "b":2} == {"b":2, "a":1}.
    assert input_hash({"a": 1, "b": 2}) == input_hash({"b": 2, "a": 1})
