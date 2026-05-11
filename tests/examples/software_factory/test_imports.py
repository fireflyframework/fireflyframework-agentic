# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Smoke import test for the software_factory package."""

from __future__ import annotations

import software_factory as sf
from software_factory.exceptions import (
    ActionInputError,
    ActionRuntimeError,
    MissingArtifactError,
)
from software_factory.io_models import RunResult


def test_software_factory_package_imports() -> None:
    assert sf is not None


def test_exceptions_import() -> None:
    assert issubclass(MissingArtifactError, ActionRuntimeError)
    assert MissingArtifactError.exit_code == 78
    assert ActionInputError.exit_code == 1


def test_run_result_model() -> None:
    r = RunResult(agent="product_owner", outputs={"pr_number": "42"}, cost_usd=0.1, tokens_in=10, tokens_out=20)
    assert r.agent == "product_owner"
    assert r.outputs == {"pr_number": "42"}
