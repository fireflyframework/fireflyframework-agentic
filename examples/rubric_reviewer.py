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

"""RubricReviewer example.

Demonstrates:
- ``RubricReviewer`` for semantic quality evaluation with a separate grader agent.
- Rubric defined as a list of natural-language pass/fail criteria.
- Isolated grader context: the grader has no access to the generator's reasoning.
- Retry loop that feeds gaps back to the generator until the rubric is satisfied.

Usage::

    uv run python examples/rubric_reviewer.py --question "What is the capital of France?"
    uv run python examples/rubric_reviewer.py --question "Explain quantum entanglement"
"""

from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.validation import RubricReviewer

load_dotenv()

MODEL = os.environ["MODEL"]

RUBRIC = [
    "The answer directly addresses the question without padding.",
    "Every factual claim is specific and concrete, not vague.",
    "The response is three sentences or fewer.",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RubricReviewer example")
    parser.add_argument("--question", default="What is the capital of France?")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    generator = FireflyAgent("generator", model=MODEL)
    grader = FireflyAgent(
        "grader",
        model=MODEL,
        instructions=(
            "You are a strict evaluator. Assess whether an output satisfies "
            "a rubric of pass/fail criteria. Be precise and objective."
        ),
    )

    reviewer = RubricReviewer(rubric=RUBRIC, grader=grader, max_iterations=3)

    result = await reviewer.review(generator, args.question)

    print(f"Answer: {result.output}")
    print(f"Attempts: {result.attempts}")
    print(f"Satisfied: {result.validation_report.valid}")
    if result.retry_history:
        print("Revision history:")
        for attempt in result.retry_history:
            print(f"  Attempt {attempt.attempt} gaps: {attempt.errors}")


if __name__ == "__main__":
    asyncio.run(main())
