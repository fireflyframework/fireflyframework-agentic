# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the action_runtime CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import agent_registry
from software_factory.__main__ import main
from software_factory.exceptions import MissingArtifactError


@pytest.fixture
def stub_agent() -> Any:
    agent = FireflyAgent(name="stub", model="test", auto_register=False)
    agent_registry.register(agent)
    yield agent
    agent_registry.unregister("stub")


def test_main_happy_path(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["action_runtime", "--agent", "stub"])
    rc = main()
    assert rc == 0


def test_main_unknown_agent_returns_nonzero(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["action_runtime", "--agent", "does-not-exist"])
    rc = main()
    assert rc == 1


def test_main_missing_artifact_returns_78(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `MissingArtifactError` raised from the agent's run() maps to exit 78."""

    async def _raise(*args: Any, **kwargs: Any) -> Any:
        raise MissingArtifactError("prd.md")

    monkeypatch.setattr(stub_agent, "run", _raise)
    monkeypatch.setattr(sys, "argv", ["action_runtime", "--agent", "stub"])
    rc = main()
    assert rc == 78
