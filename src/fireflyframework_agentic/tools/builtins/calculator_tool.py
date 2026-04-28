# Copyright 2026 Firefly Software Solutions Inc
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

"""Built-in calculator tool with safe math expression evaluation.

Uses Python's :mod:`ast` module to parse and evaluate arithmetic
expressions without calling :func:`eval`, preventing code injection.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Sequence
from typing import Any

from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol, ParameterSpec

# Supported binary operators
_BINARY_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Supported unary operators
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Safe math constants
_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}

# Safe math functions (single-argument)
_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "ceil": math.ceil,
    "floor": math.floor,
}


def _safe_eval(node: ast.expr) -> float | int:
    """Recursively evaluate an AST node containing only arithmetic."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value

    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]

    if isinstance(node, ast.BinOp):
        op_fn = _BINARY_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return op_fn(left, right)

    if isinstance(node, ast.UnaryOp):
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_fn(_safe_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError(f"Unsupported function: {ast.dump(node.func)}")
        fn = _FUNCTIONS[node.func.id]
        args = [_safe_eval(arg) for arg in node.args]
        return fn(*args)

    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


class CalculatorTool(BaseTool):
    """Safely evaluate mathematical expressions.

    Uses AST-based parsing instead of :func:`eval` to prevent code
    injection.  Supports basic arithmetic (``+``, ``-``, ``*``, ``/``,
    ``//``, ``%``, ``**``), math functions (``sqrt``, ``sin``, ``cos``,
    ``log``, etc.), and constants (``pi``, ``e``).

    Parameters:
        guards: Optional guard chain.

    Example expressions:

    * ``"2 + 3 * 4"`` → ``14``
    * ``"sqrt(144)"`` → ``12.0``
    * ``"pi * 2**2"`` → ``12.566370614359172``
    """

    def __init__(
        self,
        *,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "calculator",
            description="Safely evaluate mathematical expressions (arithmetic, functions, constants)",
            tags=["math", "calculator", "utility"],
            guards=guards,
            parameters=[
                ParameterSpec(
                    name="expression",
                    type_annotation="str",
                    description="Math expression to evaluate (e.g. '2 + 3 * 4', 'sqrt(144)')",
                    required=True,
                ),
            ],
        )

    async def _execute(self, **kwargs: Any) -> dict[str, Any]:
        expression: str = kwargs["expression"]
        try:
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree.body)
            return {"expression": expression, "result": result}
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
            return {"expression": expression, "error": str(exc)}
