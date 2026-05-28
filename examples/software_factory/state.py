# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Shared state for the software factory pipeline.

One Pydantic model carries every field the agents read or write. The only
non-default reducer is ``extend`` on ``qa_feedback`` so feedback accumulates
across QA-loop iterations instead of being overwritten on each pass.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from fireflyframework_agentic.pipeline import extend


class BuildState(BaseModel):
    request: str
    iteration: int = 0
    adr: str | None = None
    code: str | None = None
    build_status: str | None = None
    qa_status: str | None = None
    qa_feedback: Annotated[list[str], extend] = []
    release_tag: str | None = None
