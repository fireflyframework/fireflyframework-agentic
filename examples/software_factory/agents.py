# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Offline pipeline nodes that generate and verify a bounded Python project.

The recipe implements integer-cent order totals. These are ordinary deterministic
pipeline functions, not LLM agents. Every success status comes from a completed
filesystem operation, compilation, test process, or archive verification.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import py_compile
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from examples.software_factory.state import BuildState

_SOURCE = '''def total_price(unit_price_cents: int, quantity: int, discount_percent: int = 0) -> int:
    """Return an order total in cents, rounding half cents upward."""
    if isinstance(unit_price_cents, bool) or not isinstance(unit_price_cents, int):
        raise TypeError("unit_price_cents must be an integer")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError("quantity must be an integer")
    if isinstance(discount_percent, bool) or not isinstance(discount_percent, int):
        raise TypeError("discount_percent must be an integer")
    if unit_price_cents < 0 or quantity < 0:
        raise ValueError("price and quantity must be nonnegative")
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("discount_percent must be between 0 and 100")
    return (unit_price_cents * quantity * (100 - discount_percent) + 50) // 100
'''

_TESTS = """import unittest
from order_totals import total_price


class OrderTotalsTests(unittest.TestCase):
    def test_regular_order(self):
        self.assertEqual(total_price(1999, 3), 5997)

    def test_discount(self):
        self.assertEqual(total_price(1000, 2, 25), 1500)

    def test_half_cent_rounds_up(self):
        self.assertEqual(total_price(101, 1, 50), 51)

    def test_zero_and_free_orders(self):
        self.assertEqual(total_price(1999, 0), 0)
        self.assertEqual(total_price(1999, 2, 100), 0)

    def test_invalid_ranges(self):
        for args in [(-1, 1), (1, -1), (1, 1, -1), (1, 1, 101)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                total_price(*args)

    def test_integer_inputs_required(self):
        for args in [(True, 1), (1, False), (1, 1, True), (1.5, 1), (1, "2")]:
            with self.subTest(args=args), self.assertRaises(TypeError):
                total_price(*args)


if __name__ == "__main__":
    unittest.main()
"""

_ALLOWED_SYNTAX = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Expr,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.If,
    ast.Raise,
    ast.Call,
    ast.BoolOp,
    ast.Or,
    ast.And,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.Compare,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.FloorDiv,
)


def _validate_source(source: str) -> None:
    """Accept only finite arithmetic for this recipe, with no imports, I/O, or loops."""
    if len(source) > 16_384:
        raise ValueError("Recipe source exceeds 16 KiB")
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Recipe source must define only total_price")
    function = tree.body[0]
    if function.name != "total_price" or function.decorator_list:
        raise ValueError("Recipe source must define undecorated total_price")
    nodes = list(ast.walk(tree))
    if len(nodes) > 500:
        raise ValueError("Recipe source exceeds the syntax limit")
    for node in nodes:
        if not isinstance(node, _ALLOWED_SYNTAX):
            raise ValueError(f"Unsupported recipe syntax: {type(node).__name__}")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in {"isinstance", "TypeError", "ValueError"}
        ):
            raise ValueError("Recipe source may call only input-validation builtins")
        if isinstance(node, ast.BinOp) and any(
            isinstance(child, ast.Constant) and isinstance(child.value, str) for child in ast.walk(node)
        ):
            raise ValueError("Recipe arithmetic cannot operate on string literals")
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and abs(node.value) > 1_000_000_000:
            raise ValueError("Recipe integer literal exceeds the arithmetic limit")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 1024:
            raise ValueError("Recipe string literal exceeds the arithmetic limit")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def architect(state: BuildState) -> dict:
    return {
        "adr": (
            f"Request: {state.request}\n\n"
            "Recipe: a dependency-free order_totals.total_price(price_cents, quantity, discount_percent=0). "
            "Inputs are nonnegative integer cents and quantity; discounts are integer percentages from 0 to 100. "
            "Round half cents upward. Reject booleans, fractional inputs, and out-of-range values. "
            "Compile Python source and run six behavioral tests before creating a local ZIP release."
        )
    }


async def codegen(state: BuildState) -> dict:
    # An existing implementation can enter the first build; failed QA regenerates
    # the complete bounded recipe from its published contract.
    code = state.code if state.iteration == 0 and state.code is not None else _SOURCE
    return {"iteration": state.iteration + 1, "code": code, "build_status": None, "qa_status": None}


async def builder(state: BuildState) -> dict:
    if state.code is None:
        raise ValueError("No source was generated")
    _validate_source(state.code)
    root = Path(state.workspace)
    build = root / "build"
    build.mkdir(parents=True, exist_ok=True)
    source = root / "order_totals.py"
    source.write_text(state.code, encoding="utf-8")
    (root / "test_order_totals.py").write_text(_TESTS, encoding="utf-8")
    (root / "README.md").write_text(
        f"# Order totals\n\n{state.adr}\n\n"
        "Run tests: `python -m unittest discover -v`\n\n"
        "Example: `total_price(1999, 3, 10)` returns `5397` cents.\n",
        encoding="utf-8",
    )
    py_compile.compile(str(source), cfile=str(build / "order_totals.pyc"), doraise=True)
    return {"build_status": "ok", "source_sha256": _digest(source)}


async def qa(state: BuildState) -> dict:
    root = Path(state.workspace)
    source = root / "order_totals.py"
    _validate_source(source.read_text(encoding="utf-8"))
    if _digest(source) != state.source_sha256:
        raise ValueError("Project source changed after compilation")
    if (root / "test_order_totals.py").read_text(encoding="utf-8") != _TESTS:
        raise ValueError("Generated QA tests changed after compilation")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-m",
        "unittest",
        "discover",
        "-s",
        str(root.resolve()),
        "-p",
        "test_order_totals.py",
        "-v",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("QA exceeded the 10-second execution limit") from None
    output = stdout.decode("utf-8", errors="replace")
    report = {"returncode": process.returncode, "output": output, "source_sha256": state.source_sha256}
    (root / "qa-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if process.returncode != 0:
        return {"qa_status": "fail", "qa_feedback": [output[-6000:]]}
    return {"qa_status": "pass"}


async def stable_release(state: BuildState) -> dict:
    root = Path(state.workspace)
    if state.build_status != "ok" or state.qa_status != "pass":
        raise ValueError("Release requires a compiled project and passing QA")
    if _digest(root / "order_totals.py") != state.source_sha256:
        raise ValueError("Project source changed after QA")
    release_tag = f"sha256-{state.source_sha256[:12]}"
    artifact = root / f"order-totals-{release_tag}.zip"
    with ZipFile(artifact, "w", compression=ZIP_DEFLATED) as archive:
        for name in ("order_totals.py", "test_order_totals.py", "README.md", "qa-report.json"):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (root / name).read_bytes())
    with ZipFile(artifact) as archive:
        if archive.testzip() is not None:
            raise ValueError("Release archive failed its checksum check")
    return {"release_tag": release_tag, "artifact_path": str(artifact.resolve()), "artifact_sha256": _digest(artifact)}
