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

"""Classifier template agent example.

Demonstrates:
- ``create_classifier_agent`` with user-defined categories.
- ``ClassificationResult`` structured output (category, confidence, reasoning).

Usage::

    uv run python examples/classifier.py
"""

from __future__ import annotations

import asyncio

from _common import MODEL, ensure_api_key

from fireflyframework_agentic.agents.templates import create_classifier_agent

SAMPLES = [
    "My invoice shows an incorrect charge for last month's subscription.",
    "How do I reset my password on the new mobile app?",
    "I'd like to upgrade my plan to the enterprise tier.",
    "Your product is amazing, saved us hours of work!",
]


async def main() -> None:
    ensure_api_key()

    agent = create_classifier_agent(
        categories=["billing", "technical_support", "sales", "feedback"],
        descriptions={
            "billing": "Invoices, charges, payments, refunds",
            "technical_support": "Bugs, how-to questions, password resets",
            "sales": "Upgrades, new purchases, pricing inquiries",
            "feedback": "Compliments, complaints, suggestions",
        },
        model=MODEL,
    )

    print("=== Text Classifier ===\n")
    for text in SAMPLES:
        result = await agent.run(text)
        out = result.output
        print(f"Text      : {text}")
        print(f"Category  : {out.category}")
        print(f"Confidence: {out.confidence:.2f}")
        print(f"Reasoning : {out.reasoning}\n")


if __name__ == "__main__":
    asyncio.run(main())
