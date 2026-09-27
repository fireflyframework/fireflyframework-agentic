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

2. **Map-reduce via ``Send``** — document workers compute word counts
   concurrently; an aggregator totals their results through the ``extend`` reducer.

3. **HITL Pause + audit log** — build a real archive, pause before copying it
   into a local release directory, then verify its digest and resume using a
   simulated approval. ``FileAuditLog`` captures each node visit.

For the deeper software-factory walkthrough (QA feedback loop, checkpoint +
resume, Postgres / Redis checkpointer templates), see the self-contained
example package ``examples/software_factory/``.

Usage::

    uv run python examples/pipeline_state.py

No API key is required. These are deterministic local workflows, with a small
keyword rule for sentiment. The release demonstration uses only temporary files;
it does not contact a deployment service or imply a real person's approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fireflyframework_agentic.pipeline import (
    FileAuditLog,
    FileCheckpointer,
    Pause,
    PipelineBuilder,
    Send,
    extend,
)

# =============================================================================
# Scenario 1 — Branching
# =============================================================================


class SentimentState(BaseModel):
    text: str
    sentiment: str | None = None
    response: str | None = None


async def classify_sentiment(state: SentimentState) -> dict:
    words = re.findall(r"\b\w+\b", state.text.lower())
    positive = {"good", "great", "love", "amazing", "wonderful", "happy", "excellent"}
    negative = {"bad", "terrible", "hate", "awful", "horrible", "sad", "poor"}
    pos = sum(1 for word in words if word in positive)
    neg = sum(1 for word in words if word in negative)
    return {"sentiment": "positive" if pos > neg else "negative" if neg > pos else "neutral"}


async def positive_reply(state: SentimentState) -> dict:
    return {"response": "😊 Thank you for your kind words!"}


async def negative_reply(state: SentimentState) -> dict:
    return {"response": "😟 We're sorry to hear that. We'll improve!"}


async def neutral_reply(state: SentimentState) -> dict:
    return {"response": "Thank you for the feedback. Which part should we improve?"}


def route_by_sentiment(state: SentimentState) -> str:
    # The router returns the node id directly — no mapping needed.
    return f"{state.sentiment}_reply"


async def run_branching() -> None:
    print("=== 1. Branching (state mode) ===\n")

    pipeline = (
        PipelineBuilder("sentiment", state=SentimentState)
        .add_node(classify_sentiment)
        .add_node(positive_reply)
        .add_node(negative_reply)
        .add_node(neutral_reply)
        .branch(classify_sentiment, route_by_sentiment)
        .build()
    )

    for text in ["This product is great and amazing!", "The service was terrible and awful.", "The package arrived."]:
        result = await pipeline.invoke(SentimentState(text=text))
        print(f"  input:  {text!r}")
        print(f"  output: {result.state.response}\n")


# =============================================================================
# Scenario 2 — Map-reduce via Send
#
# (For a larger end-to-end scenario see ``examples/software_factory/``. It
# exercises the QA feedback loop, checkpoint + resume, and includes
# plug-and-play Postgres / Redis templates.)
# =============================================================================


class DocumentStats(BaseModel):
    text: str
    words: int
    unique_words: int
    characters: int


class MapReduceState(BaseModel):
    items: list[str] = Field(default_factory=list)
    processed: Annotated[list[DocumentStats], extend] = Field(default_factory=list)
    summary: str | None = None
    # Per-Send payload field — each worker receives its own item here.
    item: str | None = None


async def plan(state: MapReduceState) -> dict:
    items = [text.strip() for text in state.items if text.strip()]
    if not items:
        raise ValueError("Provide at least one non-empty document")
    return {"items": items}


async def process_item(state: MapReduceState) -> dict:
    if state.item is None:
        raise ValueError("The worker requires a document")
    words = re.findall(r"\b\w+\b", state.item.lower())
    stats = DocumentStats(text=state.item, words=len(words), unique_words=len(set(words)), characters=len(state.item))
    return {"processed": [stats.model_dump()]}


async def aggregate(state: MapReduceState) -> dict:
    word_count = sum(document.words for document in state.processed)
    characters = sum(document.characters for document in state.processed)
    return {"summary": f"{len(state.processed)} documents contain {word_count} words and {characters} characters."}


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
    result = await pipeline.invoke(MapReduceState(items=["Alpha beta beta.", "Small workflows compose.", " "]))
    for document in result.state.processed:
        print(f"  document: {document.model_dump()}")
    print(f"  summary: {result.state.summary}")


# =============================================================================
# Entrypoint
# =============================================================================


class HitlState(BaseModel):
    """A local artifact promotion, with an approval gate before the copy."""

    target_env: Literal["preview", "staging"]
    source_dir: str
    release_dir: str
    artifact: str | None = None
    artifact_sha256: str | None = None
    deployed_to: str | None = None


async def build_artifact(state: HitlState) -> dict:
    source = Path(state.source_dir).resolve()
    files = sorted(path for path in source.rglob("*") if path.is_file() and not path.is_symlink())
    if not files:
        raise ValueError("The source directory must contain at least one file")
    artifacts = source.parent / "artifacts"
    artifacts.mkdir(exist_ok=True)
    artifact = artifacts / f"build-{state.target_env}.tar.gz"
    with tarfile.open(artifact, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(source))
    return {"artifact": str(artifact), "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}


async def await_approval(state: HitlState) -> Pause:
    return Pause(reason=f"Approve local promotion of {state.artifact} (SHA-256 {state.artifact_sha256})?")


async def deploy_artifact(state: HitlState) -> dict:
    if state.artifact is None or state.artifact_sha256 is None:
        raise ValueError("A built artifact and its digest are required")
    artifact = Path(state.artifact)
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != state.artifact_sha256:
        raise ValueError("Artifact digest changed after the build")
    destination_dir = Path(state.release_dir) / state.target_env
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / artifact.name
    shutil.copyfile(artifact, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != state.artifact_sha256:
        raise ValueError("Promoted artifact digest does not match the build")
    return {"deployed_to": str(destination)}


async def run_hitl_with_audit() -> None:
    print("=== 3. Human-in-the-loop deploy gate with audit log ===\n")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        source.mkdir()
        (source / "index.html").write_text("<h1>Firefly local release</h1>\n")
        (source / "manifest.json").write_text('{"name": "local-release", "version": "1.0.0"}\n')
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
        first = await pipeline.invoke(
            HitlState(target_env="staging", source_dir=str(source), release_dir=str(root / "releases"))
        )
        print(f"  first run:  paused={first.paused}, paused_node={first.paused_node}")
        print(f"              reason: {first.pause_reason}")
        print(f"              run_id: {first.run_id}\n")

        print("  Simulating approval for this temporary local release.\n")

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
