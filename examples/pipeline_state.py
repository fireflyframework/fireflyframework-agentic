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

"""State-based PipelineBuilder: branching, checkpoint/resume, and Send fan-out.

Three scenarios:

1. **Branching** — same sentiment-classification workflow as
   ``examples/pipeline_branching.py``, but written with the state-mode API
   (one shared ``State`` model, ``async (state) -> dict`` nodes, one
   ``.branch(source, router)`` call instead of ``BranchStep`` + per-node
   ``condition`` lambdas).

2. **Software factory with checkpoint/resume** — a four-agent pipeline
   (architect → python_dev → deployer → evaluator) where the deployer fails
   on its first attempt. The pipeline checkpoints after each successful node,
   and a second ``invoke(run_id=...)`` resumes from the failed node instead
   of re-running the earlier agents.

3. **Map-reduce via ``Send``** — a planner dispatches one ``Send`` per work
   item to the same worker node, the workers run concurrently, and an
   aggregator runs once with all results in shared state.

Usage::

    uv run python examples/pipeline_state.py

.. note:: No OpenAI API key required — all "agents" are plain Python stubs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from fireflyframework_agentic.pipeline import (
    FileCheckpointer,
    PipelineBuilder,
    PostgresCheckpointer,
    Send,
    extend,
)

# Quiet the pipeline's own logger.exception() when we deliberately fail
# the deployer in scenario 2 — the failure is the demo, not a bug.
logging.getLogger("fireflyframework_agentic.pipeline").setLevel(logging.CRITICAL)


# =============================================================================
# Scenario 1 — Branching
# =============================================================================


class SentimentState(BaseModel):
    text: str
    sentiment: str | None = None
    response: str | None = None


async def classify_sentiment(state: SentimentState) -> dict:
    text = state.text.lower()
    positive = {"good", "great", "love", "amazing", "wonderful", "happy", "excellent"}
    negative = {"bad", "terrible", "hate", "awful", "horrible", "sad", "poor"}
    pos = sum(1 for w in text.split() if w in positive)
    neg = sum(1 for w in text.split() if w in negative)
    return {"sentiment": "positive" if pos >= neg else "negative"}


async def positive_reply(state: SentimentState) -> dict:
    return {"response": "😊 Thank you for your kind words!"}


async def negative_reply(state: SentimentState) -> dict:
    return {"response": "😟 We're sorry to hear that. We'll improve!"}


def route_by_sentiment(state: SentimentState) -> str:
    # The router returns the node id directly — no mapping needed.
    return "positive_reply" if state.sentiment == "positive" else "negative_reply"


async def run_branching() -> None:
    print("=== 1. Branching (state mode) ===\n")

    pipeline = (
        PipelineBuilder("sentiment", state=SentimentState)
        .add_node(classify_sentiment)
        .add_node(positive_reply)
        .add_node(negative_reply)
        .branch(classify_sentiment, route_by_sentiment)
        .build()
    )

    for text in ["This product is great and amazing!", "The service was terrible and awful."]:
        result = await pipeline.invoke(SentimentState(text=text))
        print(f"  input:  {text!r}")
        print(f"  output: {result.state.response}\n")


# =============================================================================
# Scenario 2 — Software factory with checkpoint/resume
# =============================================================================


class BuildState(BaseModel):
    """State threaded through a four-agent software-factory pipeline."""

    requirements: str
    spec: str | None = None
    code: str | None = None
    deploy_url: str | None = None
    evaluation: str | None = None


# A flag so the deployer fails the first time and succeeds the second.
_deployer_failed_once = {"flag": False}


async def architect(state: BuildState) -> dict:
    return {"spec": f"Architecture for: {state.requirements}"}


async def python_dev(state: BuildState) -> dict:
    return {"code": f"# code implementing\n# {state.spec}"}


async def deployer(state: BuildState) -> dict:
    if not _deployer_failed_once["flag"]:
        _deployer_failed_once["flag"] = True
        raise RuntimeError("network blip — try again")
    return {"deploy_url": "https://factory-app.example.com"}


async def evaluator(state: BuildState) -> dict:
    return {"evaluation": f"PASS — deployed at {state.deploy_url}"}


async def run_software_factory() -> None:
    print("=== 2. Software factory with checkpoint/resume ===\n")

    with tempfile.TemporaryDirectory() as tmp:
        ckpt = FileCheckpointer(Path(tmp))
        pipeline = (
            PipelineBuilder("software-factory", state=BuildState, checkpointer=ckpt)
            .add_node(architect)
            .add_node(python_dev)
            .add_node(deployer)
            .add_node(evaluator)
            .chain(architect, python_dev, deployer, evaluator)
            .build()
        )

        # First run — deployer fails after architect + python_dev complete.
        first = await pipeline.invoke(BuildState(requirements="User-management service"))
        print(f"  first run:  success={first.success}, failed_node={first.failed_node}")
        print(f"              completed: {first.completed_nodes}")
        print(f"              run_id:    {first.run_id}\n")

        # Resume — picks up at deployer, skips architect + python_dev.
        second = await pipeline.invoke(run_id=first.run_id)
        print(f"  resumed:    success={second.success}")
        print(f"              completed: {second.completed_nodes}")
        print(f"              eval:      {second.state.evaluation}\n")


# =============================================================================
# Scenario 3 — Map-reduce via Send
# =============================================================================


class MapReduceState(BaseModel):
    items: list[str] = []
    processed: Annotated[list[str], extend] = []
    summary: str | None = None
    # Per-Send payload field — each worker receives its own item here.
    item: str | None = None


async def plan(state: MapReduceState) -> dict:
    # No state mutation; the dispatch router below decides what runs next.
    return {}


async def process_item(state: MapReduceState) -> dict:
    assert state.item is not None
    return {"processed": [f"processed:{state.item}"]}


async def aggregate(state: MapReduceState) -> dict:
    return {"summary": f"Processed {len(state.processed)} items: {state.processed}"}


def dispatch(state: MapReduceState) -> list[Send]:
    # One Send per item — workers run concurrently. The ``extend`` reducer on
    # ``processed`` merges all worker outputs into one list.
    return [Send("process_item", {"item": x}) for x in state.items]


async def run_map_reduce() -> None:
    print("=== 3. Map-reduce via Send ===\n")

    pipeline = (
        PipelineBuilder("mapreduce", state=MapReduceState)
        .add_node(plan)
        .add_node(process_item)
        .add_node(aggregate)
        .add_edge(process_item, aggregate)
        .branch(plan, dispatch)
        .build()
    )
    result = await pipeline.invoke(MapReduceState(items=["alpha", "beta", "gamma", "delta"]))
    print(f"  summary: {result.state.summary}")


# =============================================================================
# Entrypoint
# =============================================================================


async def run_software_factory_postgres() -> None:
    """Optional: the same software-factory scenario backed by Postgres.

    Runs only when the ``PG_DSN`` env var is set (e.g.
    ``PG_DSN=postgresql://user:pw@localhost/firefly``). Requires the
    ``postgres`` extra: ``pip install fireflyframework-agentic[postgres]``.
    """
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        return

    print("=== 4. Software factory with PostgresCheckpointer ===\n")

    # Reset the deployer flag so this scenario starts clean.
    _deployer_failed_once["flag"] = False

    checkpointer = PostgresCheckpointer(dsn=dsn)
    pipeline = (
        PipelineBuilder("software-factory-pg", state=BuildState, checkpointer=checkpointer)
        .add_node(architect)
        .add_node(python_dev)
        .add_node(deployer)
        .add_node(evaluator)
        .chain(architect, python_dev, deployer, evaluator)
        .build()
    )
    first = await pipeline.invoke(BuildState(requirements="postgres-backed deploy"))
    print(f"  first run:  success={first.success}, failed_node={first.failed_node}")
    print(f"              run_id:    {first.run_id}\n")
    second = await pipeline.invoke(run_id=first.run_id)
    print(f"  resumed:    success={second.success}")
    print(f"              eval:      {second.state.evaluation}\n")


async def main() -> None:
    await run_branching()
    await run_software_factory()
    await run_map_reduce()
    await run_software_factory_postgres()


if __name__ == "__main__":
    asyncio.run(main())
