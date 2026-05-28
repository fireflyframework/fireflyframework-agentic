# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""End-to-end smoke test for the software_factory example.

Runs the pipeline against a tmp-dir FileCheckpointer; asserts that the
transient builder failure triggers a checkpointed failure on the first
invoke, and that resuming via ``run_id`` walks through the QA loop and
finishes with a stable release.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples.software_factory import agents
from examples.software_factory.pipeline import build_pipeline
from examples.software_factory.state import BuildState
from fireflyframework_agentic.pipeline import FileCheckpointer


@pytest.fixture(autouse=True)
def _reset_builder_attempts() -> None:
    """The builder stub uses a process-wide counter to simulate a one-shot
    transient failure. Reset it so each test sees the same starting state.
    """
    agents._BUILDER_ATTEMPTS.clear()


async def test_factory_end_to_end(tmp_path: Path) -> None:
    pipeline = build_pipeline(FileCheckpointer(tmp_path))

    first = await pipeline.invoke(BuildState(request="payments microservice"))
    assert first.success is False
    assert first.failed_node == "builder"
    assert first.state.iteration == 1
    assert first.state.build_status is None

    resumed = await pipeline.invoke(run_id=first.run_id)
    assert resumed.success is True
    assert resumed.state.release_tag == "v2026.05.28"
    assert resumed.state.qa_status == "pass"
    assert resumed.state.iteration == 2  # QA fail on iter 1 → loop → iter 2 passes
    assert resumed.state.qa_feedback == ["missing PSD2 strong-auth flow"]
