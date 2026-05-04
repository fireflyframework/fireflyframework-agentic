# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared Pydantic models for the action runtime.

Per-agent Input/Output schemas (PRD, ADR, QAReport, ...) live with the
specialized agents (Spec 3). Only the runtime-shared `RunResult` is here.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunResult(BaseModel):
    """Summary of a single agent run, written to `$GITHUB_OUTPUT` by the runtime."""

    agent: str
    outputs: dict[str, str] = Field(default_factory=dict)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
