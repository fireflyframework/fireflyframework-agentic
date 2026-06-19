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

"""Static AST safety pre-screen for guest/generated code.

This is **defense in depth, not the security boundary** — the sandbox backend
(Monty) is the boundary. The pre-screen rejects obvious sandbox-escape vectors
(dangerous imports, ``eval``/``exec``/``__import__``, dunder attribute walks)
*before* code reaches the interpreter, giving fast, legible rejections and a
second layer should a backend ever regress. Never rely on it alone.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Modules that, if importable, would breach isolation. The Monty backend already
# denies these; the pre-screen rejects them early with a clear message.
_DEFAULT_DENIED_MODULES: frozenset[str] = frozenset(
    {
        "os", "sys", "subprocess", "socket", "shutil", "importlib", "ctypes",
        "builtins", "pathlib", "io", "multiprocessing", "threading", "signal",
        "resource", "pty", "fcntl", "mmap", "gc", "inspect", "types", "code",
        "codeop", "marshal", "pickle", "shelve", "dbm", "requests", "urllib",
        "http", "ftplib", "smtplib", "asyncio", "platform", "sysconfig",
        "webbrowser", "tempfile", "glob",
    }
)

# Builtins that enable dynamic code execution or environment access.
_DEFAULT_DENIED_BUILTINS: frozenset[str] = frozenset(
    {
        "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
        "globals", "locals", "vars", "memoryview", "exit", "quit",
    }
)


@dataclass(slots=True)
class SafetyPolicy:
    """Configuration for :func:`analyze_code`.

    Attributes:
        denied_modules: Top-level module names that may not be imported.
        denied_builtins: Builtin names that may not be called/referenced.
        deny_dunder_access: Reject attribute access to dunder names
            (``x.__class__``, ``().__class__.__bases__`` …) — the classic
            sandbox-escape walk.
        allowed_modules: When set, an allowlist — only these modules may be
            imported and everything else is rejected (overrides
            ``denied_modules``).
    """

    denied_modules: frozenset[str] = _DEFAULT_DENIED_MODULES
    denied_builtins: frozenset[str] = _DEFAULT_DENIED_BUILTINS
    deny_dunder_access: bool = True
    allowed_modules: frozenset[str] | None = None


@dataclass(slots=True)
class CodeViolation:
    """A single safety finding."""

    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


@dataclass(slots=True)
class SafetyReport:
    """The result of a safety analysis."""

    safe: bool
    violations: list[CodeViolation] = field(default_factory=list)

    def messages(self) -> list[str]:
        return [str(v) for v in self.violations]


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def analyze_code(code: str, policy: SafetyPolicy | None = None) -> SafetyReport:
    """Statically analyse ``code`` and report safety violations.

    Returns a :class:`SafetyReport`; ``safe`` is ``True`` only when there are no
    violations. A syntax error is itself reported as a violation (the code could
    not be parsed and so must not run).
    """
    policy = policy or SafetyPolicy()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return SafetyReport(safe=False, violations=[CodeViolation(exc.lineno or 0, f"syntax error: {exc.msg}")])

    violations: list[CodeViolation] = []

    def _check_module(name: str, lineno: int) -> None:
        root = _module_root(name)
        if policy.allowed_modules is not None:
            if root not in policy.allowed_modules:
                violations.append(CodeViolation(lineno, f"import of '{name}' is not on the allowlist"))
        elif root in policy.denied_modules:
            violations.append(CodeViolation(lineno, f"import of '{name}' is not permitted"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            _check_module(node.module or "", node.lineno)
        elif isinstance(node, ast.Name) and node.id in policy.denied_builtins:
            violations.append(CodeViolation(node.lineno, f"use of '{node.id}' is not permitted"))
        elif isinstance(node, ast.Attribute) and policy.deny_dunder_access and _is_dunder(node.attr):
            violations.append(CodeViolation(node.lineno, f"access to dunder attribute '{node.attr}' is not permitted"))

    return SafetyReport(safe=not violations, violations=violations)
