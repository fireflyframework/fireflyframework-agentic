# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the artifact module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from software_factory.action_runtime.artifact import ArtifactStore
from software_factory.action_runtime.exceptions import MissingArtifactError


def test_factory_dir_uses_runner_temp(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    assert store.root == tmp_runner_temp


def test_read_text_returns_content(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "prd.md").write_text("# PRD\n", encoding="utf-8")
    store = ArtifactStore.from_env()
    assert store.read_text("prd.md") == "# PRD\n"


def test_read_text_missing_raises(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    with pytest.raises(MissingArtifactError, match="prd.md"):
        store.read_text("prd.md")


def test_write_text_creates_file(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    store.write_text("adr.md", "# ADR\n")
    assert (tmp_runner_temp / "adr.md").read_text() == "# ADR\n"


def test_read_json_parses(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(json.dumps({"passed": True}))
    store = ArtifactStore.from_env()
    assert store.read_json("qa_report.json") == {"passed": True}


def test_write_json_round_trip(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    store.write_json("out.json", {"x": 1, "y": [2, 3]})
    assert json.loads((tmp_runner_temp / "out.json").read_text()) == {"x": 1, "y": [2, 3]}


def test_exists(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    assert store.exists("none.txt") is False
    (tmp_runner_temp / "yes.txt").write_text("hi")
    assert store.exists("yes.txt") is True


def test_from_env_raises_without_runner_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    with pytest.raises(RuntimeError, match="RUNNER_TEMP"):
        ArtifactStore.from_env()
