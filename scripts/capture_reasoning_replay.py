#!/usr/bin/env python3
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Operator CLI: run one question against the real LLM, capture the resulting
tool-call sequence as a Tier A JSON replay fixture.

Usage::

    set -a && . .env && set +a
    uv run python scripts/capture_reasoning_replay.py \\
        q1_yoy_growth \\
        "What's the YoY revenue growth rate per business unit from 2023 to 2024?"

The output JSON lands at
``tests/examples/corpus_search/replay/<qid>.json`` and records the model's
ordered tool decisions + final answer.

What the captured JSON does NOT include:

- ``stub_return`` payloads for each ``sql_query`` / ``knowledge_search`` step.
  The Tier A replay tests need these so the stubbed corpus / structured
  retriever can hand back deterministic data. We can record the *observed*
  return strings from the trace, but those are post-truncation and lossy.
  The operator-maintainer is expected to fill them in by hand from the
  real corpus (or, for Q1–Q5, from the values in ``reasoning_fixtures.py``)
  after capture. A future iteration could lift this restriction by routing
  tool returns through a recording shim — out of scope here.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Adjust sys.path so ``scripts/`` can import test helpers without an
# editable install gymnastic.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


REPLAY_ROOT = REPO_ROOT / "tests" / "examples" / "corpus_search" / "replay"


async def _main(qid: str, question: str) -> None:
    from fireflyframework_agentic.reasoning.trace import ActionStep
    from tests.examples.corpus_search.test_corpus_query_reasoning_real_llm import (
        _build_corpus_with_fixtures,
    )

    with tempfile.TemporaryDirectory() as td:
        agent = await _build_corpus_with_fixtures(Path(td))
        try:
            answer = await agent.query(question, include_trace=True)
        finally:
            await agent.close()

        assert answer.reasoning_trace is not None, "include_trace=True returned None trace"

        decisions: list[dict] = []
        for step in answer.reasoning_trace.steps:
            if isinstance(step, ActionStep):
                decisions.append(
                    {
                        "kind": "tool_call",
                        "tool_name": step.tool_name,
                        "args": step.tool_args,
                        "stub_return": None,  # operator fills this in
                    }
                )
        decisions.append(
            {
                "kind": "final_answer",
                "text": answer.text,
                "citations": list(answer.citations),
            }
        )
        REPLAY_ROOT.mkdir(parents=True, exist_ok=True)
        out_path = REPLAY_ROOT / f"{qid}.json"
        out_path.write_text(
            json.dumps(
                {"question": question, "decisions": decisions},
                indent=2,
            )
            + "\n",
        )
        print(f"wrote {out_path}")
        print(
            "NOTE: stub_return is None on every tool_call decision — fill these "
            "in from the real corpus before relying on this fixture for Tier A "
            "replay."
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
