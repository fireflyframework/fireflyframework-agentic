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
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            raise PythonComputeError(f"dunder attribute '.{node.attr}' is not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name.startswith("__") and name.endswith("__"):
                raise PythonComputeError(f"dunder name '{name}' is not allowed")
            if name in DISALLOWED_BUILTIN_NAMES:
                raise PythonComputeError(f"call to '{name}' is not allowed")
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top not in WHITELISTED_MODULES:
                    raise PythonComputeError(f"import of '{alias.name}' is not allowed")
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".", 1)[0]
            if mod not in WHITELISTED_MODULES:
                raise PythonComputeError(f"from-import of '{node.module}' is not allowed")
