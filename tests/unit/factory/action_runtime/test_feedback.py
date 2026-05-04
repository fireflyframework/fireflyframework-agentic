# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the feedback module."""
from __future__ import annotations

import json
from pathlib import Path

from fireflyframework_agentic.factory.action_runtime.artifact import ArtifactStore
from fireflyframework_agentic.factory.action_runtime.feedback import (
    FeedbackContext,
    load_feedback,
)


def test_returns_none_when_iteration_is_one(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(json.dumps({"passed": False}))
    store = ArtifactStore.from_env()
    assert load_feedback(store, iteration=1) is None


def test_returns_none_when_report_missing(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    assert load_feedback(store, iteration=2) is None


def test_returns_context_when_present_and_iter_gt_one(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(
        json.dumps({"passed": False, "summary": "test_x failed", "failures": []})
    )
    store = ArtifactStore.from_env()
    fb = load_feedback(store, iteration=2)
    assert isinstance(fb, FeedbackContext)
    assert fb.iteration == 2
    assert fb.previous_report["summary"] == "test_x failed"
