# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Loads prior QA feedback for codegen retry iterations.

The full `QAReport` Pydantic model lives with the qa agent (Spec 3). This
module accepts the report as a free-form dict so the runtime stays
agent-agnostic; agents that consume the feedback can validate it against
their own model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.factory.action_runtime.artifact import ArtifactStore


class FeedbackContext(BaseModel):
    iteration: int
    previous_report: dict[str, Any]


def load_feedback(store: ArtifactStore, *, iteration: int) -> FeedbackContext | None:
    """Return a `FeedbackContext` if iteration > 1 and `qa_report.json` exists."""
    if iteration <= 1:
        return None
    if not store.exists("qa_report.json"):
        return None
    return FeedbackContext(
        iteration=iteration,
        previous_report=store.read_json("qa_report.json"),
    )
