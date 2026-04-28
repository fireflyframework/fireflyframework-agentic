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

"""Pipeline branching with BranchStep, PipelineEventHandler, and exponential backoff.

Demonstrates:
- ``BranchStep`` for conditional routing in a DAG pipeline.
- ``PipelineEventHandler`` for live progress monitoring.
- ``DAGNode.backoff_factor`` for exponential retry backoff.
- ``PipelineBuilder`` for fluent pipeline construction.

The pipeline classifies input text as "positive" or "negative" via a
BranchStep, then routes to the appropriate downstream handler.

Usage::

    uv run python examples/pipeline_branching.py

.. note:: This example does NOT require an OpenAI API key — it runs
   entirely locally with plain Python callables as pipeline steps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.steps import BranchStep, CallableStep

# -- Event handler that prints live progress ----------------------------------


@dataclass
class ProgressHandler:
    """Collects and prints pipeline events in real time."""

    log: list[str] = field(default_factory=list)

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        msg = f"  ▶ [{pipeline_name}] {node_id} started"
        self.log.append(msg)
        print(msg)

    async def on_node_complete(self, node_id: str, pipeline_name: str, latency_ms: float) -> None:
        msg = f"  ✔ [{pipeline_name}] {node_id} completed ({latency_ms:.1f}ms)"
        self.log.append(msg)
        print(msg)

    async def on_node_skip(self, node_id: str, pipeline_name: str, reason: str) -> None:
        msg = f"  ⏭ [{pipeline_name}] {node_id} skipped: {reason}"
        self.log.append(msg)
        print(msg)

    async def on_node_error(self, node_id: str, pipeline_name: str, error: str) -> None:
        msg = f"  ✗ [{pipeline_name}] {node_id} error: {error}"
        self.log.append(msg)
        print(msg)

    async def on_pipeline_complete(self, pipeline_name: str, success: bool, duration_ms: float) -> None:
        status = "SUCCESS" if success else "FAILED"
        msg = f"  ═ [{pipeline_name}] {status} in {duration_ms:.1f}ms"
        self.log.append(msg)
        print(msg)


# -- Pipeline steps (no LLM needed) ------------------------------------------


def sentiment_router(inputs: dict) -> str:
    """Simple keyword-based sentiment classifier."""
    text = inputs.get("input", "").lower()
    positive_words = {"good", "great", "love", "amazing", "wonderful", "happy", "excellent"}
    negative_words = {"bad", "terrible", "hate", "awful", "horrible", "sad", "poor"}
    pos = sum(1 for w in text.split() if w in positive_words)
    neg = sum(1 for w in text.split() if w in negative_words)
    return "positive" if pos >= neg else "negative"


async def positive_handler(context: PipelineContext, inputs: dict) -> str:
    branch = inputs.get("input", "")
    return f"😊 Positive response: Thank you for your kind words! (branch={branch})"


async def negative_handler(context: PipelineContext, inputs: dict) -> str:
    branch = inputs.get("input", "")
    return f"😟 Negative response: We're sorry to hear that. We'll improve! (branch={branch})"


async def summary_handler(context: PipelineContext, inputs: dict) -> str:
    """Aggregates whichever branch ran."""
    values = [v for v in inputs.values() if v is not None and v != ""]
    return f"Summary: {' | '.join(str(v) for v in values)}"


# -- Flaky step for retry/backoff demo ---------------------------------------

_retry_counter = 0


async def flaky_step(context: PipelineContext, inputs: dict) -> str:
    """Fails on first call, succeeds on retry — demonstrates backoff."""
    global _retry_counter  # noqa: PLW0603
    _retry_counter += 1
    if _retry_counter < 2:
        raise RuntimeError("Transient error — will succeed on retry")
    return "Recovered after retry!"


async def main() -> None:
    handler = ProgressHandler()

    # ── Pipeline 1: Branching ────────────────────────────────────────────
    print("=== Pipeline 1: Sentiment Branching ===\n")

    dag = (
        PipelineBuilder("sentiment-branch")
        .add_node("classify", BranchStep(router=sentiment_router))
        .add_node(
            "handle_positive",
            CallableStep(positive_handler),
            condition=lambda ctx: ctx.get_node_result("classify").output == "positive",
        )
        .add_node(
            "handle_negative",
            CallableStep(negative_handler),
            condition=lambda ctx: ctx.get_node_result("classify").output == "negative",
        )
        .add_edge("classify", "handle_positive")
        .add_edge("classify", "handle_negative")
        .build_dag()
    )
    engine = PipelineEngine(dag, event_handler=handler)

    for text in ["This product is great and amazing!", "The service was terrible and awful."]:
        print(f"\nInput: {text!r}")
        result = await engine.run(inputs=text)
        print(f"Final : {result.final_output}\n")

    # ── Pipeline 2: Retry with exponential backoff ───────────────────────
    print("\n=== Pipeline 2: Retry with Exponential Backoff ===\n")

    global _retry_counter  # noqa: PLW0603
    _retry_counter = 0
    handler2 = ProgressHandler()

    dag = DAG("retry-demo")
    dag.add_node(
        DAGNode(
            node_id="flaky",
            step=CallableStep(flaky_step),
            retry_max=2,
            backoff_factor=0.01,  # Fast for demo
        )
    )

    async def _done(ctx: PipelineContext, inp: dict) -> str:
        return f"Pipeline complete: {inp.get('input', '')}"

    dag.add_node(DAGNode(node_id="done", step=CallableStep(_done)))
    dag.add_edge(DAGEdge(source="flaky", target="done"))

    engine2 = PipelineEngine(dag, event_handler=handler2)
    result = await engine2.run(inputs="test-with-retry")
    print(f"\nFinal : {result.final_output}")
    print(f"Success: {result.success}")


if __name__ == "__main__":
    asyncio.run(main())
