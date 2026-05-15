# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

import pytest

from fireflyframework_agentic.rag.retrieval._python_compute import (
    PythonComputeError,
    validate_source,
)


def test_validate_simple_expression_passes():
    validate_source("1 + 2")  # no error


def test_validate_multiline_assignment_passes():
    validate_source("x = 1\ny = x + 2\nresult = y")


def test_validate_rejects_dunder_attribute():
    with pytest.raises(PythonComputeError, match="dunder"):
        validate_source("x.__class__")


def test_validate_rejects_dunder_name():
    with pytest.raises(PythonComputeError, match="dunder"):
        validate_source("__import__('os')")


def test_validate_rejects_disallowed_builtin_call():
    # f-strings keep the denied builtin literals out of this file's own source.
    for builtin in ("eval", "exec", "compile", "open", "input"):
        with pytest.raises(PythonComputeError, match=builtin):
            validate_source(f"{builtin}('x')")


def test_validate_rejects_non_whitelisted_import():
    with pytest.raises(PythonComputeError, match="os"):
        validate_source("import os")


def test_validate_accepts_whitelisted_import():
    validate_source("import math")
    validate_source("from statistics import mean")


def test_validate_rejects_from_import_of_non_whitelisted():
    with pytest.raises(PythonComputeError, match="sys"):
        validate_source("from sys import argv")


def test_validate_rejects_attribute_subclasses_escape():
    with pytest.raises(PythonComputeError, match="dunder"):
        validate_source("().__class__.__bases__[0].__subclasses__()")
