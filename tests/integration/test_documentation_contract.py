"""Keep published Python snippets syntactically valid and their Firefly imports real."""

from __future__ import annotations

import ast
import doctest
import importlib
import re
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_FENCE = re.compile(r"^```(?:python|py)\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def _snippets():
    paths = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "tests" / "README.md",
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "examples").rglob("README.md")),
    ]
    for path in paths:
        if path.name.lower() == "changelog.md":
            continue
        source = path.read_text()
        for match in _FENCE.finditer(source):
            code = textwrap.dedent(match[1])
            if re.search(r"^>>> ", code, re.MULTILINE):
                code = "\n".join(example.source for example in doctest.DocTestParser().get_examples(code))
            line = source.count("\n", 0, match.start()) + 1
            yield pytest.param(code, id=f"{path.relative_to(ROOT)}:{line}")


@pytest.mark.parametrize("code", list(_snippets()))
def test_documented_python_and_framework_imports(code):
    tree = ast.parse(code)
    contracts = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(getattr(base, "id", getattr(base, "attr", "")) in {"Protocol", "ABC"} for base in node.bases)
        for child in ast.walk(node)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and id(node) not in contracts:
            abstract = any(
                getattr(decorator, "id", getattr(decorator, "attr", "")) == "abstractmethod"
                for decorator in node.decorator_list
            )
            body = [
                statement
                for statement in node.body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                )
            ]
            unfinished = (
                not body
                or len(body) == 1
                and (
                    isinstance(body[0], ast.Pass)
                    or (
                        isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and body[0].value.value is Ellipsis
                    )
                )
            )
            assert abstract or not unfinished, f"{node.name} has no implementation"
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fireflyframework_agentic"):
            module = importlib.import_module(node.module)
            for alias in node.names:
                if alias.name != "*":
                    assert hasattr(module, alias.name), f"{node.module} does not export {alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("fireflyframework_agentic"):
                    importlib.import_module(alias.name)
