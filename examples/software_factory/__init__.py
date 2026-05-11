# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Agentic SDLC software factory — example application built on fireflyframework-agentic.

Wraps `FireflyAgent` instances as reusable GitHub Actions.
"""

from __future__ import annotations

from .exceptions import (
    ActionInputError,
    ActionRuntimeError,
    MissingArtifactError,
)
from .io_models import RunResult
from .runner import run_agent

__all__ = [
    "ActionInputError",
    "ActionRuntimeError",
    "MissingArtifactError",
    "RunResult",
    "run_agent",
]
