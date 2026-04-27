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

"""Quality-of-Service guards: confidence scoring, consistency, and grounding.

These guards wrap agent outputs and detect potential hallucinations or
low-quality extractions before they propagate through the pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.types import AgentLike

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# QoS result model
# ---------------------------------------------------------------------------


class QoSResult(BaseModel):
    """Outcome of a QoS check."""

    passed: bool
    confidence: float = 0.0
    consistency_score: float = 0.0
    grounding_score: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ConfidenceScorer
# ---------------------------------------------------------------------------


class ConfidenceScorer:
    """Score LLM output confidence via self-evaluation.

    Asks the LLM to rate its own confidence on a 0.0-1.0 scale.

    Parameters:
        agent: An agent with an async ``run(prompt)`` method.
        prompt_template: Custom prompt template for self-evaluation.
    """

    def __init__(
        self,
        agent: AgentLike,
        *,
        prompt_template: str | None = None,
    ) -> None:
        self._agent = agent
        self._template = prompt_template or (
            "Rate your confidence in the following output on a scale of 0.0 to 1.0.\n"
            "Consider accuracy, completeness, and whether any information might be hallucinated.\n\n"
            "Output to evaluate:\n{output}\n\n"
            "Respond with ONLY a decimal number between 0.0 and 1.0."
        )

    async def score(self, output: str) -> float:
        """Return a confidence score between 0.0 and 1.0."""
        prompt = self._template.format(output=output)
        result = await self._agent.run(prompt)
        text = str(result.output if hasattr(result, "output") else result).strip()
        try:
            return max(0.0, min(1.0, float(text)))
        except ValueError:
            logger.warning("Could not parse confidence score from: %s", text[:100])
            return 0.5


# ---------------------------------------------------------------------------
# ConsistencyChecker
# ---------------------------------------------------------------------------


class ConsistencyChecker:
    """Check output consistency by running the same prompt multiple times.

    Measures agreement across N runs.  High agreement suggests reliable
    output; low agreement may indicate hallucination.

    Parameters:
        agent: An agent with an async ``run(prompt)`` method.
        num_runs: Number of times to run the prompt (default 3).
    """

    def __init__(self, agent: AgentLike, *, num_runs: int = 3) -> None:
        self._agent = agent
        self._num_runs = max(2, num_runs)

    async def check(self, prompt: str | Sequence[Any], **kwargs: Any) -> tuple[float, list[str]]:
        """Run *prompt* multiple times and return (consistency_score, outputs).

        The consistency score is the pairwise overlap ratio averaged across
        all output pairs (simplified Jaccard similarity on words).
        """
        outputs: list[str] = []
        for _ in range(self._num_runs):
            result = await self._agent.run(prompt, **kwargs)
            outputs.append(str(result.output if hasattr(result, "output") else result))

        if len(outputs) < 2:
            return 1.0, outputs

        # Pairwise word-level Jaccard similarity
        similarities: list[float] = []
        for i in range(len(outputs)):
            for j in range(i + 1, len(outputs)):
                set_a = set(outputs[i].lower().split())
                set_b = set(outputs[j].lower().split())
                if set_a or set_b:
                    similarities.append(len(set_a & set_b) / len(set_a | set_b))
                else:
                    similarities.append(1.0)

        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
        return avg_similarity, outputs


# ---------------------------------------------------------------------------
# GroundingChecker
# ---------------------------------------------------------------------------


class GroundingChecker:
    """Verify that extracted fields are grounded in the source document.

    Checks whether extracted values appear (or closely appear) in the
    original source text, which helps detect hallucinated extractions.

    Parameters:
        case_sensitive: Whether grounding checks are case-sensitive.
        min_grounding_ratio: Minimum fraction of fields that must be
            grounded for the overall check to pass (default 0.8).
    """

    def __init__(
        self,
        *,
        case_sensitive: bool = False,
        min_grounding_ratio: float = 0.8,
    ) -> None:
        self._case_sensitive = case_sensitive
        self._min_ratio = min_grounding_ratio

    def check(
        self,
        source_text: str,
        extracted_fields: dict[str, Any],
    ) -> tuple[float, dict[str, bool]]:
        """Check grounding and return (grounding_score, field_grounded_map).

        Parameters:
            source_text: The original document text.
            extracted_fields: Dict of field_name -> extracted_value.

        Returns:
            A tuple of (score, per-field grounding map).
        """
        if not extracted_fields:
            return 1.0, {}

        source = source_text if self._case_sensitive else source_text.lower()
        grounded: dict[str, bool] = {}

        for field_name, value in extracted_fields.items():
            if value is None:
                grounded[field_name] = True  # None fields are trivially grounded
                continue
            str_val = str(value)
            check_val = str_val if self._case_sensitive else str_val.lower()

            # Direct substring check
            if check_val in source:
                grounded[field_name] = True
                continue

            # Word overlap check: at least 60% of value words in source
            val_words = set(check_val.split())
            source_words = set(source.split())
            if val_words and len(val_words & source_words) / len(val_words) >= 0.6:
                grounded[field_name] = True
                continue

            grounded[field_name] = False

        grounding_ratio = sum(grounded.values()) / len(grounded) if grounded else 1.0
        return grounding_ratio, grounded


# ---------------------------------------------------------------------------
# QoSGuard
# ---------------------------------------------------------------------------


class QoSGuard:
    """Composable guard that evaluates agent output quality.

    Combines confidence scoring, consistency checking, and grounding
    verification.  Rejects results below configurable thresholds.

    Parameters:
        confidence_scorer: Optional :class:`ConfidenceScorer`.
        consistency_checker: Optional :class:`ConsistencyChecker`.
        grounding_checker: Optional :class:`GroundingChecker`.
        min_confidence: Minimum confidence threshold (default 0.7).
        min_consistency: Minimum consistency threshold (default 0.6).
        min_grounding: Minimum grounding threshold (default 0.8).
    """

    def __init__(
        self,
        *,
        confidence_scorer: ConfidenceScorer | None = None,
        consistency_checker: ConsistencyChecker | None = None,
        grounding_checker: GroundingChecker | None = None,
        min_confidence: float = 0.7,
        min_consistency: float = 0.6,
        min_grounding: float = 0.8,
    ) -> None:
        self._confidence_scorer = confidence_scorer
        self._consistency_checker = consistency_checker
        self._grounding_checker = grounding_checker
        self._min_confidence = min_confidence
        self._min_consistency = min_consistency
        self._min_grounding = min_grounding

    async def evaluate(
        self,
        output: str,
        *,
        prompt: str | Sequence[Any] | None = None,
        source_text: str | None = None,
        extracted_fields: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> QoSResult:
        """Evaluate the quality of *output*.

        Parameters:
            output: The LLM output to evaluate.
            prompt: Original prompt (needed for consistency checking).
            source_text: Original source document (needed for grounding).
            extracted_fields: Extracted field dict (needed for grounding).

        Returns:
            A :class:`QoSResult` with scores and pass/fail status.
        """
        confidence = 0.0
        consistency = 0.0
        grounding = 0.0
        details: dict[str, Any] = {}
        passed = True

        # Confidence check
        if self._confidence_scorer is not None:
            confidence = await self._confidence_scorer.score(output)
            details["confidence"] = confidence
            if confidence < self._min_confidence:
                passed = False
                details["confidence_failed"] = True

        # Consistency check
        if self._consistency_checker is not None and prompt is not None:
            consistency, outputs = await self._consistency_checker.check(prompt, **kwargs)
            details["consistency"] = consistency
            details["consistency_outputs"] = len(outputs)
            if consistency < self._min_consistency:
                passed = False
                details["consistency_failed"] = True

        # Grounding check
        if self._grounding_checker is not None and source_text is not None and extracted_fields is not None:
            grounding, field_map = self._grounding_checker.check(source_text, extracted_fields)
            details["grounding"] = grounding
            details["ungrounded_fields"] = [k for k, v in field_map.items() if not v]
            if grounding < self._min_grounding:
                passed = False
                details["grounding_failed"] = True

        return QoSResult(
            passed=passed,
            confidence=confidence,
            consistency_score=consistency,
            grounding_score=grounding,
            details=details,
        )
