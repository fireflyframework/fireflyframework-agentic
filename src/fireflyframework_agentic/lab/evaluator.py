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

"""Evaluation orchestrator for running agents against datasets with scoring."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from fireflyframework_agentic.lab.dataset import EvalDataset
from fireflyframework_agentic.types import AgentLike

# A scorer takes (expected, actual) and returns a float score
Scorer = Callable[[str, str], float]


class EvalResult(BaseModel):
    """Result for a single evaluation case."""

    input: str
    expected: str
    actual: str
    score: float = 0.0


class EvalReport(BaseModel):
    """Summary report of an evaluation run."""

    agent_name: str
    total_cases: int = 0
    avg_score: float = 0.0
    results: list[EvalResult] = []


def exact_match_scorer(expected: str, actual: str) -> float:
    """Return 1.0 if expected equals actual, else 0.0."""
    return 1.0 if expected.strip() == actual.strip() else 0.0


class EvalOrchestrator:
    """Run evaluations with configurable scorers.

    Parameters:
        scorer: A callable ``(expected, actual) -> float``.
    """

    def __init__(self, scorer: Scorer | None = None) -> None:
        self._scorer = scorer or exact_match_scorer

    async def evaluate(self, agent: AgentLike, dataset: EvalDataset, agent_name: str = "") -> EvalReport:
        """Evaluate *agent* against *dataset*."""
        name = agent_name or getattr(agent, "name", "unknown")
        results: list[EvalResult] = []

        for case in dataset.cases:
            result = await agent.run(case.input)
            actual = str(result.output if hasattr(result, "output") else result)
            score = self._scorer(case.expected_output, actual)
            results.append(
                EvalResult(
                    input=case.input,
                    expected=case.expected_output,
                    actual=actual,
                    score=score,
                )
            )

        avg = sum(r.score for r in results) / len(results) if results else 0
        return EvalReport(
            agent_name=name,
            total_cases=len(results),
            avg_score=avg,
            results=results,
        )
