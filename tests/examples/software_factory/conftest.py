# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Shared fixtures for software_factory action_runtime tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp file and point GITHUB_OUTPUT at it."""
    out = tmp_path / "github_output.txt"
    out.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    return out


@pytest.fixture
def tmp_runner_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create $RUNNER_TEMP/factory/ and point RUNNER_TEMP at the parent."""
    runner_temp = tmp_path / "runner_temp"
    factory_dir = runner_temp / "factory"
    factory_dir.mkdir(parents=True)
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    return factory_dir
