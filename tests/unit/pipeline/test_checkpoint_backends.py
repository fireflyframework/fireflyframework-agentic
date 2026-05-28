# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the framework's File Checkpointer.

The Postgres and Redis backends used to live in the framework and were
exercised here with mocks; both moved to plug-and-play templates under
``examples/software_factory/checkpointers/`` (apps that need them copy the
file into their repo and test it against their own infra).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.pipeline import (
    CheckpointRecord,
    FileCheckpointer,
    PipelineBuilder,
    StatePipeline,
)

# =============================================================================
# FileCheckpointer
# =============================================================================


def test_file_checkpointer_save_and_load_latest(tmp_path) -> None:
    ckpt = FileCheckpointer(tmp_path / "ckpt")

    ckpt.save(
        CheckpointRecord(
            pipeline_name="p",
            run_id="r",
            sequence=1,
            node_id="a",
            state={"k": 1},
            completed_nodes=["a"],
        )
    )
    ckpt.save(
        CheckpointRecord(
            pipeline_name="p",
            run_id="r",
            sequence=2,
            node_id="b",
            state={"k": 2},
            completed_nodes=["a", "b"],
        )
    )

    latest = ckpt.load_latest("p", "r")
    assert latest is not None
    assert latest.node_id == "b"
    assert latest.state == {"k": 2}
    assert latest.completed_nodes == ["a", "b"]


def test_file_checkpointer_load_latest_unknown_run_returns_none(tmp_path) -> None:
    assert FileCheckpointer(tmp_path).load_latest("p", "missing") is None


def test_file_checkpointer_list_runs(tmp_path) -> None:
    ckpt = FileCheckpointer(tmp_path / "ckpt")
    for run_id in ("rA", "rB"):
        ckpt.save(
            CheckpointRecord(
                pipeline_name="p",
                run_id=run_id,
                sequence=1,
                node_id="a",
                state={},
                completed_nodes=["a"],
            )
        )
    assert ckpt.list_runs("p") == ["rA", "rB"]
    assert ckpt.list_runs("missing") == []


def test_file_checkpointer_paused_record_round_trips(tmp_path) -> None:
    ckpt = FileCheckpointer(tmp_path)
    ckpt.save(
        CheckpointRecord(
            pipeline_name="p",
            run_id="r",
            sequence=1,
            node_id="await_approval",
            state={"x": 1},
            completed_nodes=["a", "await_approval"],
            paused=True,
            pause_reason="waiting on human",
        )
    )
    latest = ckpt.load_latest("p", "r")
    assert latest is not None
    assert latest.paused is True
    assert latest.pause_reason == "waiting on human"


# =============================================================================
# Protocol conformance — software-factory scenario against File backend
# =============================================================================


class FactoryState(BaseModel):
    requirements: str
    spec: str | None = None
    code: str | None = None
    deploy_url: str | None = None
    evaluation: str | None = None


def _build_factory(checkpointer) -> StatePipeline:
    """Construct the canonical 4-step agent pipeline that fails on first deploy."""
    state_flag = {"failed_once": False}

    async def architect(state: FactoryState) -> dict:
        return {"spec": f"spec for {state.requirements}"}

    async def python_dev(state: FactoryState) -> dict:
        return {"code": f"# code for {state.spec}"}

    async def deployer(state: FactoryState) -> dict:
        if not state_flag["failed_once"]:
            state_flag["failed_once"] = True
            raise RuntimeError("blip")
        return {"deploy_url": "https://app"}

    async def evaluator(state: FactoryState) -> dict:
        return {"evaluation": f"PASS {state.deploy_url}"}

    pipeline = (
        PipelineBuilder("factory", state=FactoryState, checkpointer=checkpointer)
        .add_node(architect)
        .add_node(python_dev)
        .add_node(deployer)
        .add_node(evaluator)
        .chain(architect, python_dev, deployer, evaluator)
        .build()
    )
    assert isinstance(pipeline, StatePipeline)
    return pipeline


@pytest.mark.asyncio
async def test_file_backend_supports_fail_and_resume(tmp_path) -> None:
    """Deployer fails on its first call → run is checkpointed → resume completes."""
    backend = FileCheckpointer(tmp_path / "ckpt")
    pipeline = _build_factory(backend)

    first = await pipeline.invoke(FactoryState(requirements="users service"))
    assert not first.success
    assert first.failed_node == "deployer"
    assert first.completed_nodes == ["architect", "python_dev"]

    second = await pipeline.invoke(run_id=first.run_id)
    assert second.success
    assert second.completed_nodes == ["architect", "python_dev", "deployer", "evaluator"]
    assert second.state.evaluation == "PASS https://app"
