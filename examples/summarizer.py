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

"""Summarizer template agent example.

Demonstrates:
- ``create_summarizer_agent`` with tuneable length, style, and format.
- Summarising a text passage.

Usage::

    uv run python examples/summarizer.py
"""

from __future__ import annotations

import asyncio

from _common import MODEL, ensure_api_key

from fireflyframework_agentic.agents.templates import create_summarizer_agent

ARTICLE = """\
Artificial intelligence has undergone a dramatic transformation over the past
decade. Early systems relied on hand-crafted rules and expert knowledge, but
the advent of deep learning shifted the paradigm toward data-driven approaches.
Transformer architectures, introduced in 2017, became the foundation of modern
language models. These models learn statistical patterns from vast text corpora
and can generate remarkably fluent prose, translate languages, summarise
documents, and answer complex questions. However, challenges remain: models can
hallucinate facts, struggle with multi-step reasoning, and reflect biases
present in training data. Researchers are now exploring techniques like
reinforcement learning from human feedback (RLHF), chain-of-thought prompting,
and retrieval-augmented generation (RAG) to mitigate these limitations and push
AI toward more reliable, grounded, and transparent behaviour.
"""


async def main() -> None:
    ensure_api_key()

    agent = create_summarizer_agent(
        model=MODEL,
        max_length="short",
        style="professional",
        output_format="bullets",
    )

    print("=== Summarizer (short, bullets) ===\n")
    result = await agent.run(ARTICLE)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
