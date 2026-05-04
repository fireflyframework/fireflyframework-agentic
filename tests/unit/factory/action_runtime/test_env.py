# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for env.read_action_inputs."""
from __future__ import annotations

import os

import pytest

from fireflyframework_agentic.factory.action_runtime.env import read_action_inputs


def test_returns_lowercased_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_INTENT", "build a thing")
    monkeypatch.setenv("INPUT_PR_NUMBER", "42")
    inputs = read_action_inputs()
    assert inputs == {"intent": "build a thing", "pr_number": "42"}


def test_ignores_non_input_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Clear any pre-existing INPUT_* vars
    for k in list(os.environ.keys()):
        if k.startswith("INPUT_"):
            monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("INPUT_X", "1")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GITHUB_OUTPUT", "/tmp/x")
    inputs = read_action_inputs()
    assert inputs == {"x": "1"}


def test_empty_when_no_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os_environ_keys_starting_with_input()):
        monkeypatch.delenv(k, raising=False)
    inputs = read_action_inputs()
    assert inputs == {}


def os_environ_keys_starting_with_input() -> list[str]:
    return [k for k in os.environ if k.startswith("INPUT_")]
