# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Phase-3c HITL tests: Pause + approve_pause resume + on_node_pause event."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline import (
    FileCheckpointer,
    Pause,
    PipelineBuilder,
    StatePipeline,
    extend,
)


class DeployState(BaseModel):
    requirements: str = ""
    spec: str | None = None
    approved: Annotated[list[str], extend] = []
    deployed: bool = False


@dataclass
class PauseRecorder:
    events: list[tuple] = field(default_factory=list)

    async def on_node_pause(self, pipeline_name: str, run_id: str, node_id: str, reason: str) -> None:
        self.events.append(("pause", node_id, reason))


# --- core pause/resume ------------------------------------------------------


@pytest.mark.asyncio
async def test_node_returning_pause_halts_pipeline(tmp_path: Path) -> None:
    async def architect(state: DeployState) -> dict:
        return {"spec": "v1"}

    async def gate(state: DeployState) -> Pause:
        return Pause(reason="awaiting deploy approval")

    async def deploy(state: DeployState) -> dict:
        return {"deployed": True}

    ckpt = FileCheckpointer(tmp_path)
    pipeline = (
        PipelineBuilder("hitl", state=DeployState, checkpointer=ckpt)
        .add_node(architect)
        .add_node(gate)
        .add_node(deploy)
        .chain(architect, gate, deploy)
        .build()
    )
    assert isinstance(pipeline, StatePipeline)

    result = await pipeline.invoke(DeployState(requirements="user-mgmt"))
    assert result.paused is True
    assert result.paused_node == "gate"
    assert result.pause_reason == "awaiting deploy approval"
    assert result.success is False  # paused != success
    assert result.state.deployed is False  # deploy did NOT run
    assert result.completed_nodes == ["architect", "gate"]


@pytest.mark.asyncio
async def test_resume_without_approve_pause_raises(tmp_path: Path) -> None:
    async def gate(state: DeployState) -> Pause:
        return Pause(reason="block here")

    pipeline = (
        PipelineBuilder("hitl", state=DeployState, checkpointer=FileCheckpointer(tmp_path)).add_node(gate).build()
    )
    first = await pipeline.invoke(DeployState())
    assert first.paused is True

    with pytest.raises(PipelineError, match="approve_pause=True"):
        await pipeline.invoke(run_id=first.run_id)


@pytest.mark.asyncio
async def test_resume_with_approve_pause_continues_from_successor(tmp_path: Path) -> None:
    fail_once = {"flag": False}

    async def architect(state: DeployState) -> dict:
        if fail_once["flag"]:
            raise AssertionError("architect should NOT re-run on resume")
        return {"spec": "v1"}

    async def gate(state: DeployState) -> Pause:
        if fail_once["flag"]:
            raise AssertionError("gate should NOT re-run on resume")
        return Pause(reason="approve please")

    async def deploy(state: DeployState) -> dict:
        return {"deployed": True}

    pipeline = (
        PipelineBuilder("hitl", state=DeployState, checkpointer=FileCheckpointer(tmp_path))
        .add_node(architect)
        .add_node(gate)
        .add_node(deploy)
        .chain(architect, gate, deploy)
        .build()
    )
    first = await pipeline.invoke(DeployState(requirements="x"))
    assert first.paused is True
    fail_once["flag"] = True  # ensure neither architect nor gate re-runs

    second = await pipeline.invoke(run_id=first.run_id, approve_pause=True)
    assert second.success is True
    assert second.state.deployed is True
    assert second.completed_nodes == ["architect", "gate", "deploy"]


@pytest.mark.asyncio
async def test_on_node_pause_event_fires(tmp_path: Path) -> None:
    async def gate(state: DeployState) -> Pause:
        return Pause(reason="hold")

    handler = PauseRecorder()
    pipeline = (
        PipelineBuilder(
            "hitl",
            state=DeployState,
            checkpointer=FileCheckpointer(tmp_path),
            event_handler=handler,  # type: ignore[arg-type]
        )
        .add_node(gate)
        .build()
    )
    await pipeline.invoke(DeployState())
    assert handler.events == [("pause", "gate", "hold")]


# --- backward compat -------------------------------------------------------


@pytest.mark.asyncio
async def test_paused_checkpoint_loads_when_pause_fields_missing(tmp_path: Path) -> None:
    """An existing checkpoint without paused/pause_reason fields still loads."""
    from fireflyframework_agentic.pipeline.checkpoint import CheckpointRecord

    # Round-trip a record produced from a dict that omits the new fields —
    # mirrors what an existing on-disk checkpoint from a pre-3c version looks like.
    raw = {
        "pipeline_name": "old",
        "run_id": "legacy",
        "node_id": "n",
        "sequence": 1,
        "state": {"requirements": "x"},
        "completed_nodes": ["n"],
    }
    record = CheckpointRecord.model_validate(raw)
    assert record.paused is False
    assert record.pause_reason is None


# --- a paused pipeline can still resume after non-pause failures -----------


@pytest.mark.asyncio
async def test_pause_then_resume_then_error_then_resume(tmp_path: Path) -> None:
    """End-to-end: pause, approve, then a subsequent failure, then retry."""
    counters = {"deploy_fail": False}

    async def gate(state: DeployState) -> Pause:
        return Pause(reason="approve")

    async def deploy(state: DeployState) -> dict:
        if not counters["deploy_fail"]:
            counters["deploy_fail"] = True
            raise RuntimeError("flaky")
        return {"deployed": True}

    pipeline = (
        PipelineBuilder("hitl", state=DeployState, checkpointer=FileCheckpointer(tmp_path))
        .add_node(gate)
        .add_node(deploy)
        .chain(gate, deploy)
        .build()
    )
    paused = await pipeline.invoke(DeployState())
    assert paused.paused

    failed = await pipeline.invoke(run_id=paused.run_id, approve_pause=True)
    assert not failed.success
    assert failed.failed_node == "deploy"

    succeeded = await pipeline.invoke(run_id=paused.run_id, approve_pause=True)
    # The deploy checkpoint at this point isn't marked paused, but the gate
    # checkpoint still is. approve_pause is needed because load_latest may
    # still return the older paused checkpoint OR the newer one depending on
    # backend sort order — both backends sort by sequence so the latest is
    # the failed-deploy record. The check passes either way: if the latest is
    # paused, approve_pause is required; if not, approve_pause is ignored.
    assert succeeded.success is True
    assert succeeded.state.deployed is True
