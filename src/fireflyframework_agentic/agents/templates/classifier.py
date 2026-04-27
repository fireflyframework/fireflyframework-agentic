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

"""Pre-built classifier agent template.

Creates a :class:`FireflyAgent` that classifies text into user-provided
categories and returns a structured result with category and confidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent


class ClassificationResult(BaseModel):
    """Structured output from the classifier agent.

    Attributes:
        category: The predicted category label.
        confidence: Confidence score between 0.0 and 1.0.
        reasoning: Brief explanation of why this category was chosen.
    """

    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


def create_classifier_agent(
    categories: Sequence[str],
    *,
    name: str = "classifier",
    model: str | Model | None = None,
    descriptions: dict[str, str] | None = None,
    multi_label: bool = False,
    extra_instructions: str = "",
    tools: Sequence[Any] = (),
    auto_register: bool = True,
    **kwargs: Any,
) -> FireflyAgent[Any, ClassificationResult]:
    """Create a text classification agent.

    Parameters:
        categories: The allowed category labels.
        name: Agent name (default ``"classifier"``).
        model: LLM model string or :class:`pydantic_ai.models.Model` instance;
            falls back to the framework default.
        descriptions: Optional mapping of category name to a human-readable
            description to help the model distinguish categories.
        multi_label: If *True*, allow assigning multiple categories
            (returns the most confident one in the structured output).
        extra_instructions: Additional instructions appended to the system prompt.
        tools: Extra tools to attach to the agent.
        auto_register: Whether to register in the global agent registry.
        **kwargs: Forwarded to :class:`FireflyAgent`.

    Returns:
        A configured :class:`FireflyAgent` that outputs :class:`ClassificationResult`.
    """
    cat_list = "\n".join(f"- {cat}: {descriptions.get(cat, '')}" if descriptions else f"- {cat}" for cat in categories)

    multi_note = (
        "You may consider multiple categories but return the single best match."
        if not multi_label
        else "Multiple categories may apply. Return the most confident one."
    )

    instructions = (
        "You are a precise text classification assistant.\n"
        "Classify the input text into exactly one of these categories:\n"
        f"{cat_list}\n\n"
        f"{multi_note}\n"
        "Return the category name exactly as listed above.\n"
        "Provide a confidence score between 0.0 and 1.0.\n"
        "Include brief reasoning for your classification."
    )
    if extra_instructions:
        instructions += f"\n{extra_instructions}"

    return FireflyAgent(
        name,
        model=model,
        instructions=instructions,
        output_type=ClassificationResult,
        description=f"Classifies text into categories: {', '.join(categories)}",
        tags=["classifier", "nlp", "template"],
        tools=tools,
        auto_register=auto_register,
        **kwargs,
    )
