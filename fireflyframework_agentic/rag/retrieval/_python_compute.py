# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Restricted Python sandbox for the corpus reasoning agent's python_compute tool.

AST-validated against a denylist before execution. Pragmatic — not adversarial.
We trust our own model, not an attacker. See spec
``docs/superpowers/specs/2026-05-14-tool-using-corpus-agent-design.md``.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import calendar
import collections
import dataclasses
import datetime as _dt
import decimal
import enum
import fractions
import functools
import io
import itertools
import json as _json
import math
import operator
import random
import re
import statistics
import string
import textwrap
import threading
import unicodedata
from contextlib import redirect_stdout
from typing import Any

try:
    import numpy as _numpy_mod
except ImportError:  # pragma: no cover - optional dep
    _numpy_mod = None  # type: ignore[assignment]

try:
    import pandas as _pandas_mod
except ImportError:  # pragma: no cover - optional dep
    _pandas_mod = None  # type: ignore[assignment]

WHITELISTED_MODULES: frozenset[str] = frozenset(
    {
        "math",
        "statistics",
        "decimal",
        "fractions",
        "datetime",
        "calendar",
        "re",
        "string",
        "textwrap",
        "unicodedata",
        "json",
        "collections",
        "itertools",
        "functools",
        "operator",
        "dataclasses",
        "enum",
        "numpy",
        "pandas",
    }
)

DISALLOWED_BUILTIN_NAMES: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "help",
        "dir",
        "vars",
        "globals",
        "locals",
    }
)

# Attribute names that perform filesystem / network IO when invoked on the
# whitelisted modules (numpy / pandas) or instances built from them. These
# are denied regardless of the receiver because attribute targets can be
# rebound (``df = pd.DataFrame(...); df.to_X(...)``); checking only the
# ``Name.id`` of the receiver would miss any chained or aliased call.
#
# Threat model: an LLM consuming retrieved corpus chunks reads
# attacker-influenced content. Without these guards, a prompt-injected
# chunk could direct the sandbox at host files via ``pd.read_csv``,
# ``np.fromfile``, etc., or trigger deserialisation-time code paths
# via the ``read_p*``/``to_p*`` family (an arbitrary-code surface).
DISALLOWED_ATTRIBUTE_NAMES: frozenset[str] = frozenset(
    {
        # pandas IO: read from disk or network
        "read_csv",
        "read_pickle",
        "read_json",
        "read_sql",
        "read_sql_query",
        "read_sql_table",
        "read_table",
        "read_excel",
        "read_html",
        "read_xml",
        "read_feather",
        "read_parquet",
        "read_orc",
        "read_hdf",
        "read_sas",
        "read_spss",
        "read_stata",
        "read_gbq",
        "read_fwf",
        "read_clipboard",
        "read_msgpack",
        # pandas IO: write to disk
        "to_pickle",
        "to_csv",
        "to_json",
        "to_sql",
        "to_excel",
        "to_html",
        "to_xml",
        "to_feather",
        "to_parquet",
        "to_orc",
        "to_hdf",
        "to_sas",
        "to_spss",
        "to_stata",
        "to_gbq",
        "to_clipboard",
        "to_msgpack",
        # numpy IO: read from disk
        "fromfile",
        "loadtxt",
        "load",
        "memmap",
        "genfromtxt",
        # numpy IO: write to disk
        "save",
        "savetxt",
        "savez",
        "savez_compressed",
        "tofile",
    }
)

# String literals that, when fed to ``str.format()`` / ``str.format_map()``
# / ``__format__``, enumerate Python's class hierarchy and reach back to
# unsafe primitives. They never appear in legitimate compute and signal
# format-string sandbox escape research.
SUSPICIOUS_FORMAT_TOKENS: frozenset[str] = frozenset(
    {"__class__", "__bases__", "__mro__", "__subclasses__", "__globals__", "__builtins__"}
)


class PythonComputeError(Exception):
    """Raised by the validator when source contains a denied AST pattern."""


def validate_source(source: str) -> None:
    """Parse ``source`` and walk its AST, raising :class:`PythonComputeError` on
    any denied pattern. Pure function — no execution. Always parses in exec
    mode so multi-statement source is accepted.
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise PythonComputeError(f"syntax error: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            raise PythonComputeError(f"dunder name '{node.id}' is not allowed")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise PythonComputeError(f"dunder attribute '.{node.attr}' is not allowed")
            # Block filesystem / network IO entry points on numpy / pandas
            # regardless of the receiver. ``pd.read_csv`` and
            # ``df.to_pickle`` both go through here.
            if node.attr in DISALLOWED_ATTRIBUTE_NAMES:
                raise PythonComputeError(
                    f"attribute '.{node.attr}' is not allowed (filesystem / network IO is denied in the sandbox)"
                )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name.startswith("__") and name.endswith("__"):
                raise PythonComputeError(f"dunder name '{name}' is not allowed")
            if name in DISALLOWED_BUILTIN_NAMES:
                raise PythonComputeError(f"call to '{name}' is not allowed")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Block format-string sandbox-escape literals like
            # '{0.__class__.__bases__}' — these never appear in legitimate
            # compute but reach back to unsafe primitives via str.format.
            for token in SUSPICIOUS_FORMAT_TOKENS:
                if token in node.value:
                    raise PythonComputeError(
                        f"string literal contains suspicious format token '{token}' (sandbox-escape research surface)"
                    )
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top not in WHITELISTED_MODULES:
                    raise PythonComputeError(f"import of '{alias.name}' is not allowed")
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".", 1)[0]
            if mod not in WHITELISTED_MODULES:
                raise PythonComputeError(f"from-import of '{node.module}' is not allowed")


# Sandbox-boundary aliases. These two Python builtins are exactly the
# call sites we want a security reviewer to read: a compiled AST that has
# already passed validate_source().
_RUN_BLOCK = _builtins.exec  # run a compiled exec-mode AST in our namespace
_RUN_EXPR = _builtins.eval  # evaluate a compiled expression in our namespace

ALLOWED_BUILTINS: frozenset[str] = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "chr",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "frozenset",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "ord",
        "pow",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)


def _build_namespace(data: dict[str, Any] | None) -> dict[str, Any]:
    """Build the locals/globals for one run. Imports are lazy so a missing
    numpy/pandas surfaces a clear error rather than a module-load failure.
    """
    safe_builtins: dict[str, Any] = {name: getattr(_builtins, name) for name in ALLOWED_BUILTINS}
    # __import__ is needed at runtime when the source contains `import X` or
    # `from X import Y` — Python's import machinery looks it up in builtins.
    # Static imports are already gated by validate_source against WHITELISTED_MODULES,
    # and dynamic invocation (the literal call `__import__(...)`) is blocked by the
    # validator's dunder-name rule.
    safe_builtins["__import__"] = _builtins.__import__
    ns: dict[str, Any] = {"__builtins__": safe_builtins}

    ns.update(
        {
            "math": math,
            "statistics": statistics,
            "decimal": decimal,
            "fractions": fractions,
            "datetime": _dt,
            "calendar": calendar,
            "re": re,
            "string": string,
            "textwrap": textwrap,
            "unicodedata": unicodedata,
            "json": _json,
            "collections": collections,
            "itertools": itertools,
            "functools": functools,
            "operator": operator,
            "dataclasses": dataclasses,
            "enum": enum,
            # Per-call deterministic random source; host state untouched.
            "random": random.Random(0),
        }
    )

    if _numpy_mod is None:
        raise RuntimeError("install fireflyframework-agentic[reasoning-eval] to use python_compute")
    ns["np"] = _numpy_mod
    ns["numpy"] = _numpy_mod
    if _pandas_mod is None:
        raise RuntimeError("install fireflyframework-agentic[reasoning-eval] to use python_compute")
    ns["pd"] = _pandas_mod
    ns["pandas"] = _pandas_mod

    if data:
        ns.update(data)
    return ns


def _df_to_markdown(df: Any) -> str:
    """Render a pandas DataFrame as a minimal markdown table. Inline rather
    than ``df.to_markdown(index=False)`` so we don't take a dep on tabulate.
    """
    cols = [str(c) for c in df.columns]
    rows = [[str(v) for v in row] for row in df.itertuples(index=False, name=None)]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return f"{header}\n{sep}\n{body}" if body else f"{header}\n{sep}"


def _render(value: Any) -> str:
    """Render a result value for return to the LLM. Special-cases DataFrame and
    ndarray to keep traces readable; falls back to ``repr``.

    Both optional-dep imports are wrapped in ``try/except ImportError``
    defensively: ``_build_namespace`` raises with a clear install hint when
    numpy/pandas are missing, so in practice the sandbox refuses to run
    before we ever reach ``_render``. Keeping the guards here means a
    future caller that bypasses the namespace builder (e.g. a unit test
    that hands ``_render`` a value directly) still degrades gracefully to
    ``repr`` instead of crashing.
    """
    if _pandas_mod is not None and isinstance(value, _pandas_mod.DataFrame):
        return _df_to_markdown(value)
    if _numpy_mod is not None and isinstance(value, _numpy_mod.ndarray):
        with _numpy_mod.printoptions(threshold=200, edgeitems=3):
            return repr(value)
    return repr(value)


def _truncate(text: str, cap: int) -> str:
    # ``cap`` is a character count, not a byte count. For multi-byte
    # output (CJK, emoji) the on-the-wire size is larger but truncation
    # happens at the readable boundary, which is what the LLM cares about.
    if len(text) <= cap:
        return text
    excess = len(text) - cap
    return text[:cap] + f"… (truncated, {excess} more chars)"


def run_python_compute(
    source: str,
    data: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 5.0,
    output_cap_chars: int = 8192,
) -> str:
    """Validate, execute, and render restricted Python.

    Returns the rendered result (or last-expression value if ``result`` is not
    set), with captured stdout prepended. On any failure (denied AST, syntax,
    runtime, timeout) returns a string starting with ``"python_compute error:"``
    or ``"python_compute timeout"`` so the LLM can self-correct without the
    loop dying.
    """
    try:
        validate_source(source)
    except PythonComputeError as exc:
        return f"python_compute error: {exc}"

    try:
        ns = _build_namespace(data)
    except RuntimeError as exc:
        return f"python_compute error: {exc}"

    tree = ast.parse(source, mode="exec")
    last = tree.body[-1] if tree.body else None
    explicitly_assigns_result = any(
        isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "result" for t in s.targets)
        for s in tree.body
    )
    # Bind the trailing expression node directly so the type narrows from
    # ``ast.stmt`` to ``ast.Expr`` and ``.value`` access type-checks cleanly.
    last_expr: ast.Expr | None = last if isinstance(last, ast.Expr) and not explicitly_assigns_result else None

    buf = io.StringIO()
    holder: list[Any] = []
    err: list[BaseException] = []

    def _runner() -> None:
        try:
            with redirect_stdout(buf):
                if last_expr is not None:
                    body_tree = ast.Module(body=tree.body[:-1], type_ignores=[])
                    expr_tree = ast.Expression(body=last_expr.value)
                    ast.fix_missing_locations(body_tree)
                    ast.fix_missing_locations(expr_tree)
                    _RUN_BLOCK(compile(body_tree, "<python_compute>", "exec"), ns)
                    holder.append(_RUN_EXPR(compile(expr_tree, "<python_compute>", "eval"), ns))
                else:
                    _RUN_BLOCK(compile(tree, "<python_compute>", "exec"), ns)
                    holder.append(ns.get("result"))
        # We deliberately catch BaseException rather than Exception. The
        # sandbox is meant to confine *any* exit from the LLM-authored
        # source so the host stays up: that includes SystemExit (which
        # ``raise SystemExit`` from sandboxed code would otherwise
        # terminate the host process), GeneratorExit, and anything else
        # subclassed off BaseException. We run on a daemon worker thread,
        # not the main thread, so signal-driven KeyboardInterrupt cannot
        # land here in practice (Python delivers signals only to the main
        # thread), and the usual "don't swallow KeyboardInterrupt" rule
        # doesn't apply.
        except BaseException as exc:  # noqa: BLE001 — see comment above
            err.append(exc)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        return f"python_compute timeout after {timeout_seconds}s"
    if err:
        return f"python_compute error: {type(err[0]).__name__}: {err[0]}"

    parts: list[str] = []
    stdout = buf.getvalue()
    if stdout:
        parts.append(stdout.rstrip("\n"))
    parts.append(_render(holder[0] if holder else None))
    combined = "\n".join(parts)
    return _truncate(combined, output_cap_chars)
