# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""End-to-end test for runner.run_agent using a built-in TestModel-backed agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.exceptions import AgentNotFoundError
from fireflyframework_agentic.factory.action_runtime.runner import run_agent


@pytest.fixture
def stub_agent() -> Any:
    """Register a stub agent backed by Pydantic-AI's built-in TestModel."""
    agent = FireflyAgent(name="stub", model="test", auto_register=False)
    agent_registry.register(agent)
    yield agent
    agent_registry.unregister("stub")


def _read_outputs(path: Path) -> dict[str, str]:
    """Parse the simple `key=value\\n` form (heredoc not used in these tests)."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k] = v
    return out


def test_run_agent_writes_outputs(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INPUT_INTENT", "build a thing")
    monkeypatch.setenv("INPUT_ITERATION", "1")

    result = asyncio.run(run_agent("stub"))

    assert result.agent == "stub"
    outputs = _read_outputs(tmp_github_output)
    assert outputs["agent"] == "stub"
    assert int(outputs["tokens_in"]) >= 0
    assert int(outputs["tokens_out"]) >= 0
    assert outputs["iteration"] == "1"
    assert outputs["feedback_used"] == "false"
    # cost_usd is formatted as a fixed-point string
    assert "cost_usd" in outputs


def test_run_agent_unknown_name_raises(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
) -> None:
    with pytest.raises(AgentNotFoundError):
        asyncio.run(run_agent("does-not-exist"))


def test_run_agent_loads_feedback_when_iteration_gt_one(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(json.dumps({"passed": False, "summary": "the test failed"}))
    monkeypatch.setenv("INPUT_INTENT", "fix it")
    monkeypatch.setenv("INPUT_ITERATION", "2")

    result = asyncio.run(run_agent("stub"))

    outputs = _read_outputs(tmp_github_output)
    assert outputs["iteration"] == "2"
    assert outputs["feedback_used"] == "true"
    assert result.agent == "stub"
