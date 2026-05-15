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


from fireflyframework_agentic.rag.retrieval._python_compute import run_python_compute  # noqa: E402


def test_run_returns_result_binding():
    out = run_python_compute("result = 1 + 2")
    assert "3" in out


def test_run_returns_last_expression_when_no_result():
    out = run_python_compute("1 + 2")
    assert "3" in out


def test_run_returns_none_when_no_expression():
    out = run_python_compute("x = 1")
    assert "None" in out


def test_run_binds_data_as_locals():
    out = run_python_compute("result = sum(values)", data={"values": [1, 2, 3]})
    assert "6" in out


def test_run_captures_print_output():
    out = run_python_compute("print('hello')\nresult = 1")
    assert "hello" in out
    assert "1" in out


def test_run_uses_per_call_random_seed():
    import random as host_random

    host_state = host_random.getstate()
    out1 = run_python_compute("result = random.random()")
    out2 = run_python_compute("result = random.random()")
    assert out1 == out2  # deterministic: fresh Random(0) each call
    assert host_random.getstate() == host_state  # host state untouched


def test_run_numpy_works():
    out = run_python_compute("import numpy as np\nresult = float(np.mean([1.0, 2.0, 3.0]))")
    assert "2.0" in out


def test_run_pandas_dataframe_renders_as_markdown():
    out = run_python_compute("import pandas as pd\nresult = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})")
    assert "|" in out and "a" in out and "b" in out


def test_run_denied_pattern_returns_error_string():
    out = run_python_compute("__import__('os')")
    assert out.startswith("python_compute error:")


def test_run_syntax_error_returns_error_string():
    out = run_python_compute("def (oops:")
    assert out.startswith("python_compute error:")


def test_run_undefined_name_returns_error_string():
    out = run_python_compute("result = undefined_thing")
    assert out.startswith("python_compute error:")


def test_run_timeout_returns_error_string():
    out = run_python_compute("while True:\n    pass", timeout_seconds=0.2)
    assert out.startswith("python_compute timeout") or out.startswith("python_compute error:")


def test_run_output_cap_truncates():
    out = run_python_compute("result = list(range(1000))", output_cap_bytes=50)
    assert "truncated" in out
    assert len(out) <= 100  # cap + suffix wiggle
