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

"""State-based PipelineBuilder quick-start: branching, Send fan-out, HITL Pause.

Three short scenarios in one file:

1. **Branching** — sentiment-classification workflow with one ``.branch(...)``
   call (vs ``BranchStep`` + per-node ``condition`` lambdas in port-based mode).

2. **Map-reduce via ``Send``** — a planner dispatches one ``Send`` per work
   item; workers run concurrently; an aggregator runs once with all results
   merged via the ``extend`` reducer.

3. **HITL Pause + audit log** — a deploy gate that returns ``Pause(...)`` to
   wait for human approval; resume with ``approve_pause=True``; a
   ``FileAuditLog`` captures every node visit with its status.

For the deeper software-factory walkthrough (QA feedback loop, checkpoint +
resume, Postgres / Redis checkpointer templates), see the self-contained
example package ``examples/software_factory/``.

Usage::

    uv run python examples/pipeline_state.py

.. note:: No OpenAI API key required — all "agents" are plain Python stubs.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from fireflyframework_agentic.pipeline import (
    FileAuditLog,
    FileCheckpointer,
    Pause,
    PipelineBuilder,
    Send,
    extend,
)

# Quiet the pipeline's own logger.exception() when we deliberately exercise
# a node failure — the failure is part of the demo, not a bug.
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
# Scenario 2 — Map-reduce via Send
#
# (The software-factory scenario that used to live here has its own folder
# now: ``examples/software_factory/``. It exercises the QA feedback loop,
# checkpoint + resume, and includes plug-and-play Postgres / Redis templates.)
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
    print("=== 2. Map-reduce via Send ===\n")

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


class HitlState(BaseModel):
    """State threaded through a deploy pipeline gated by human approval."""

    target_env: str
    artifact: str | None = None
    deployed_to: str | None = None


async def build_artifact(state: HitlState) -> dict:
    return {"artifact": f"build-{state.target_env}.tar.gz"}


async def await_approval(state: HitlState) -> Pause:
    return Pause(reason=f"awaiting human approval to deploy {state.artifact} to {state.target_env}")


async def deploy_artifact(state: HitlState) -> dict:
    return {"deployed_to": f"https://{state.target_env}.example.com"}


async def run_hitl_with_audit() -> None:
    print("=== 3. Human-in-the-loop deploy gate with audit log ===\n")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ckpt = FileCheckpointer(root / "ckpt")
        audit = FileAuditLog(root / "audit")
        pipeline = (
            PipelineBuilder(
                "hitl-deploy",
                state=HitlState,
                checkpointer=ckpt,
                audit_log=audit,
            )
            .add_node(build_artifact)
            .add_node(await_approval)
            .add_node(deploy_artifact)
            .chain(build_artifact, await_approval, deploy_artifact)
            .build()
        )

        # First run halts at the approval gate.
        first = await pipeline.invoke(HitlState(target_env="prod"))
        print(f"  first run:  paused={first.paused}, paused_node={first.paused_node}")
        print(f"              reason: {first.pause_reason}")
        print(f"              run_id: {first.run_id}\n")

        # ...time passes; a human reviews and approves...
        print("  (human reviews and approves)\n")

        # Resume with explicit approval.
        done = await pipeline.invoke(run_id=first.run_id, approve_pause=True)
        print(f"  resumed:    success={done.success}, deployed_to={done.state.deployed_to}")
        print(f"              completed: {done.completed_nodes}\n")

        # Audit log captures every node visit with its status.
        entries = audit.list_entries("hitl-deploy", first.run_id)
        print("  audit trail:")
        for e in entries:
            extra = f" reason={e.pause_reason!r}" if e.pause_reason else ""
            print(f"    seq={e.sequence} node={e.node_id} status={e.status}{extra}")


async def main() -> None:
    await run_branching()
    await run_map_reduce()
    await run_hitl_with_audit()


if __name__ == "__main__":
    asyncio.run(main())
