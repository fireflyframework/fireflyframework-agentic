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

"""Evaluation engine for testing pipelines against JSONL datasets.

Compiles a :class:`~fireflyframework_genai.studio.codegen.models.GraphModel`,
runs each test case through the resulting pipeline, and compares outputs
against expected values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """A single test case from a JSONL dataset."""

    input: str
    expected_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of running a single test case through a pipeline."""

    input: str
    expected_output: str
    actual_output: str
    passed: bool
    error: str = ""


@dataclass
class EvaluationResult:
    """Aggregate result of running a pipeline against a dataset."""

    dataset_name: str
    total: int
    passed: int
    failed: int
    error_count: int
    results: list[TestResult]

    @property
    def pass_rate(self) -> float:
        """Return the pass rate as a percentage (0-100)."""
        if self.total == 0:
            return 0.0
        return round((self.passed / self.total) * 100, 1)


def load_dataset(path: Path) -> list[TestCase]:
    """Load test cases from a JSONL file.

    Each line must be a JSON object with at minimum an ``"input"`` field.
    Optional fields: ``"expected_output"``, plus any extra keys stored
    as ``metadata``.

    Raises
    ------
    ValueError
        If the file is empty or contains invalid JSON lines.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    cases: list[TestCase] = []
    text = path.read_text(encoding="utf-8")

    for lineno, line in enumerate(text.strip().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {lineno}: {exc}") from exc

        if "input" not in obj:
            raise ValueError(f"Line {lineno} is missing required 'input' field")

        cases.append(
            TestCase(
                input=str(obj["input"]),
                expected_output=str(obj.get("expected_output", "")),
                metadata={k: v for k, v in obj.items() if k not in {"input", "expected_output"}},
            )
        )

    if not cases:
        raise ValueError("Dataset file is empty")

    return cases


def compare_outputs(expected: str, actual: str) -> bool:
    """Compare expected and actual outputs.

    When ``expected`` is empty, the test passes unconditionally (no assertion).
    Otherwise a case-insensitive, whitespace-normalized comparison is used.
    """
    if not expected:
        return True
    return _normalize(expected) == _normalize(actual)


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, collapse whitespace."""
    return " ".join(text.lower().split())


async def run_evaluation(
    graph_data: dict[str, Any],
    cases: list[TestCase],
) -> EvaluationResult:
    """Run a compiled pipeline against a list of test cases.

    Parameters
    ----------
    graph_data:
        Raw graph dict that will be validated into a
        :class:`~fireflyframework_genai.studio.codegen.models.GraphModel`.
    cases:
        The test cases to evaluate.

    Returns
    -------
    EvaluationResult
        Aggregate result with per-case details.
    """
    from fireflyframework_genai.studio.codegen.models import GraphModel
    from fireflyframework_genai.studio.execution.compiler import CompilationError, compile_graph

    graph = GraphModel.model_validate(graph_data)
    try:
        engine = compile_graph(graph)
    except CompilationError as exc:
        # All cases fail if the graph can't compile
        return EvaluationResult(
            dataset_name="",
            total=len(cases),
            passed=0,
            failed=0,
            error_count=len(cases),
            results=[
                TestResult(
                    input=c.input,
                    expected_output=c.expected_output,
                    actual_output="",
                    passed=False,
                    error=f"Compilation error: {exc}",
                )
                for c in cases
            ],
        )

    results: list[TestResult] = []
    passed = 0
    failed = 0
    error_count = 0

    for case in cases:
        try:
            result = await engine.run(inputs=case.input)
            # Extract the output from the last node
            actual = ""
            if result.outputs:
                last_node = list(result.outputs.values())[-1]
                actual = str(last_node.output) if last_node.output is not None else ""

            is_pass = compare_outputs(case.expected_output, actual)
            if is_pass:
                passed += 1
            else:
                failed += 1

            results.append(
                TestResult(
                    input=case.input,
                    expected_output=case.expected_output,
                    actual_output=actual,
                    passed=is_pass,
                )
            )
        except Exception as exc:
            error_count += 1
            results.append(
                TestResult(
                    input=case.input,
                    expected_output=case.expected_output,
                    actual_output="",
                    passed=False,
                    error=str(exc),
                )
            )

    return EvaluationResult(
        dataset_name="",
        total=len(cases),
        passed=passed,
        failed=failed,
        error_count=error_count,
        results=results,
    )
