# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""The offline factory must build, test, and release actual Python artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from examples.software_factory import agents
from examples.software_factory.pipeline import build_pipeline
from examples.software_factory.state import BuildState
from fireflyframework_agentic.pipeline import FileCheckpointer


async def test_factory_releases_a_tested_importable_project(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    result = await build_pipeline(FileCheckpointer(tmp_path / "checkpoints")).invoke(
        BuildState(request="Integer-cent order totals with discounts", workspace=str(workspace))
    )
    assert result.success
    assert result.state.iteration == 1
    assert result.state.build_status == "ok"
    assert result.state.qa_status == "pass"
    artifact = Path(result.state.artifact_path)
    assert artifact.is_file()
    assert result.state.artifact_sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    report = json.loads((workspace / "qa-report.json").read_text())
    assert report["returncode"] == 0
    assert "Ran 6 tests" in report["output"]
    with ZipFile(artifact) as archive:
        assert set(archive.namelist()) == {"order_totals.py", "test_order_totals.py", "README.md", "qa-report.json"}
        archive.extractall(tmp_path / "unpacked")
    process = subprocess.run(
        [sys.executable, "-I", "-m", "unittest", "discover", "-s", str(tmp_path / "unpacked"), "-v"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr


async def test_real_build_failure_resumes_and_qa_repairs_incomplete_input(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    blocker = workspace / "build"
    blocker.write_text("A real file prevents creation of the build directory.")
    pipeline = build_pipeline(FileCheckpointer(tmp_path / "checkpoints"))
    first = await pipeline.invoke(
        BuildState(
            request="Order totals",
            workspace=str(workspace),
            code="def total_price(unit_price_cents, quantity, discount_percent=0):\n    return unit_price_cents * quantity\n",
        )
    )
    assert not first.success
    assert first.failed_node == "builder"
    assert first.state.iteration == 1
    blocker.unlink()

    resumed = await pipeline.invoke(run_id=first.run_id)

    assert resumed.success
    assert resumed.state.iteration == 2
    assert resumed.state.qa_status == "pass"
    assert resumed.state.qa_feedback
    assert "FAIL" in resumed.state.qa_feedback[0]
    assert Path(resumed.state.artifact_path).exists()


async def test_builder_rejects_code_outside_the_bounded_recipe(tmp_path: Path) -> None:
    state = BuildState(request="Order totals", workspace=str(tmp_path), code="import os\nos.remove('important')\n")
    with pytest.raises(ValueError, match="source|syntax|Import"):
        await agents.builder(state)
    assert not (tmp_path / "order_totals.py").exists()


async def test_release_refuses_a_changed_project_after_qa(tmp_path: Path) -> None:
    result = await build_pipeline(FileCheckpointer(tmp_path / "checkpoints")).invoke(
        BuildState(request="Order totals", workspace=str(tmp_path / "project"))
    )
    assert result.success
    source = Path(result.state.workspace) / "order_totals.py"
    source.write_text(source.read_text() + "\n# changed after QA\n")
    with pytest.raises(ValueError, match="changed|digest"):
        await agents.stable_release(result.state)


async def test_qa_only_runs_its_generated_test_module(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "test_unrelated.py").write_text("raise RuntimeError('unrelated project must not be executed')\n")
    result = await build_pipeline(FileCheckpointer(tmp_path / "checkpoints")).invoke(
        BuildState(request="Order totals", workspace=str(workspace))
    )
    assert result.success
    assert result.state.iteration == 1


@pytest.mark.parametrize("body", ["return 'x' * 1000000000", "return total_price(1, 1)"])
async def test_builder_rejects_non_numeric_or_recursive_expressions(tmp_path: Path, body: str) -> None:
    state = BuildState(request="Order totals", workspace=str(tmp_path), code=f"def total_price(a, b):\n    {body}\n")
    with pytest.raises(ValueError):
        await agents.builder(state)


def test_command_line_keeps_inspectable_artifacts_and_audit(tmp_path: Path) -> None:
    workspace = tmp_path / "cli-project"
    process = subprocess.run(
        [sys.executable, "-m", "examples.software_factory", "--workspace", str(workspace)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr
    summary = json.loads((workspace / "run.json").read_text())
    assert summary["success"] is True
    assert Path(summary["artifact_path"]).is_file()
    assert list((workspace / ".audit").rglob("*.jsonl"))
