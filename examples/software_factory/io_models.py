# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Shared Pydantic models for the action runtime."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunResult(BaseModel):
    """Summary of a single agent run, written to `$GITHUB_OUTPUT` by the runtime."""

    agent: str
    outputs: dict[str, str] = Field(default_factory=dict)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
