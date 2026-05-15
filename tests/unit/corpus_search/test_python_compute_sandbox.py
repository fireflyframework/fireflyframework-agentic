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
    out = run_python_compute("result = list(range(1000))", output_cap_chars=50)
    assert "truncated" in out
    assert len(out) <= 100  # cap + suffix wiggle


# ---- C2: pandas/numpy IO is denied at the AST level --------------------
#
# Threat model: an LLM consuming retrieved corpus chunks reads
# attacker-influenced content. Without the DISALLOWED_ATTRIBUTE_NAMES
# guards, a prompt-injected chunk could direct the sandbox at host files
# via ``pd.read_csv('/etc/passwd')`` or trigger an arbitrary-code surface
# via ``pd.read_pickle(...)``. The validator denies these at parse time.


def test_pandas_read_csv_is_denied():
    """Filesystem read via pandas — the canonical exfil vector."""
    with pytest.raises(PythonComputeError, match="read_csv"):
        validate_source("import pandas as pd\npd.read_csv('/etc/passwd')")


def test_pandas_read_pickle_is_denied():
    """Reading a pickle file is an arbitrary-code-execution surface; the
    sandbox must reject the entry point before the code runs."""
    with pytest.raises(PythonComputeError, match="read_pickle"):
        validate_source("import pandas as pd\npd.read_pickle('/tmp/x.pkl')")


def test_pandas_to_pickle_via_instance_method_is_denied():
    """Attribute denylist is receiver-independent: a DataFrame method call
    must be denied even though the receiver is not ``pd`` directly."""
    src = "import pandas as pd\ndf = pd.DataFrame({'a': [1]})\ndf.to_pickle('/tmp/x.pkl')"
    with pytest.raises(PythonComputeError, match="to_pickle"):
        validate_source(src)


def test_numpy_fromfile_is_denied():
    with pytest.raises(PythonComputeError, match="fromfile"):
        validate_source("import numpy as np\nnp.fromfile('/etc/passwd')")


def test_numpy_load_is_denied():
    """np.load on a .npy file can deserialise pickled Python objects,
    same arbitrary-code surface as pd.read_pickle."""
    with pytest.raises(PythonComputeError, match="load"):
        validate_source("import numpy as np\nnp.load('/tmp/x.npy')")


def test_pandas_to_csv_to_attacker_path_is_denied():
    """Filesystem write: the LLM should not be able to dump arbitrary
    files in writable locations."""
    src = "import pandas as pd\npd.DataFrame({'a':[1]}).to_csv('/tmp/exfil.csv')"
    with pytest.raises(PythonComputeError, match="to_csv"):
        validate_source(src)


def test_legitimate_dataframe_arithmetic_still_works():
    """Sanity guard: the denylist must NOT block legitimate compute. A
    DataFrame constructed in-memory and aggregated should pass."""
    src = (
        "import pandas as pd\n"
        "df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})\n"
        "result = float(df['x'].mean() + df['y'].std())"
    )
    validate_source(src)  # must not raise
    out = run_python_compute(src)
    assert "error" not in out.lower(), f"expected clean compute, got: {out}"


# ---- I1: format-string class-hierarchy enumeration is denied -----------


def test_format_class_lookup_string_is_denied():
    """``'{0.__class__.__bases__}'.format(())`` enumerates Python's class
    hierarchy via str.format — the canonical sandbox-escape research probe.
    The dunder filter catches ``.__class__`` only as AST attribute access;
    when it's a string literal fed to format, we need a constant-scan."""
    with pytest.raises(PythonComputeError, match="format token"):
        validate_source("'{0.__class__.__bases__}'.format(())")


def test_format_globals_lookup_string_is_denied():
    with pytest.raises(PythonComputeError, match="format token"):
        validate_source("'{0.__globals__}'.format(0)")


def test_innocent_strings_pass():
    """Plain string literals must not trip the format-token denylist."""
    validate_source("result = 'hello world'")
    validate_source("name = 'Alice'\ngreeting = f'Hi, {name}'")
