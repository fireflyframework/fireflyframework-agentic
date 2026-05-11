# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Typed errors raised by the action runtime."""

from __future__ import annotations

from fireflyframework_agentic.exceptions import FireflyAgenticError


class ActionRuntimeError(FireflyAgenticError):
    """Base class for action-runtime errors."""

    exit_code: int = 1


class MissingArtifactError(ActionRuntimeError):
    """A required artifact was not found in `$RUNNER_TEMP/factory/`."""

    exit_code: int = 78  # GitHub Actions "skipped" exit code


class ActionInputError(ActionRuntimeError):
    """An `INPUT_*` env var was missing or could not be parsed."""

    exit_code: int = 1
