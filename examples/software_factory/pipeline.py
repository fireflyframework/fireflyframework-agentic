# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Wire the software-factory DAG.

The pipeline:

    architect → codegen → builder → qa ──(qa_router)──▶ stable_release
                                      │
                                      └──── qa_status='fail' ──▶ codegen (cycle)

``qa_router`` is the one piece of routing logic — it implements the QA
feedback loop with a hard cap of ``recursion_limit=3``.
"""

from __future__ import annotations

from examples.software_factory.agents import (
    architect,
    builder,
    codegen,
    qa,
    stable_release,
)
from examples.software_factory.progress import ProgressHandler
from examples.software_factory.state import BuildState
from fireflyframework_agentic.pipeline import (
    Checkpointer,
    PipelineBuilder,
    PipelineEngine,
)


def qa_router(state: BuildState) -> str:
    """Route on QA outcome — pass → release, fail → codegen (cycle)."""
    return "stable_release" if state.qa_status == "pass" else "codegen"


def build_pipeline(checkpointer: Checkpointer) -> PipelineEngine:
    pipeline = (
        PipelineBuilder(
            "software-factory",
            state=BuildState,
            checkpointer=checkpointer,
            recursion_limit=3,
            event_handler=ProgressHandler(),
        )
        .add_node(architect)
        .add_node(codegen)
        .add_node(builder)
        .add_node(qa)
        .add_node(stable_release)
        .add_edge("architect", "codegen")
        .add_edge("codegen", "builder")
        .add_edge("builder", "qa")
        .branch("qa", qa_router)
        .build()
    )
    return pipeline
