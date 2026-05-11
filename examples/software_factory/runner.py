# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Top-level entrypoint that runs a registered agent end-to-end inside an Action."""

from __future__ import annotations

import json
import logging
from typing import Any

from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.security import default_output_guard

from .artifact import ArtifactStore
from .env import read_action_inputs
from .feedback import FeedbackContext, load_feedback
from .github_outputs import write_output
from .io_models import RunResult

logger = logging.getLogger(__name__)


def _compose_prompt(inputs: dict[str, str], feedback: FeedbackContext | None) -> str:
    """Build a default prompt from raw inputs + optional feedback."""
    lines = ["# Inputs", ""]
    for k, v in sorted(inputs.items()):
        lines.append(f"## {k}\n\n{v}\n")
    if feedback is not None:
        lines.append("# Previous QA Report")
        lines.append("")
        lines.append(f"Iteration: {feedback.iteration}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(feedback.previous_report, indent=2, sort_keys=True))
        lines.append("```")
    return "\n".join(lines)


def _extract_text(result: Any) -> str:
    output = getattr(result, "output", None)
    return str(output) if output is not None else str(result)


def _extract_usage(result: Any) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) from a pydantic_ai run result."""
    usage_fn = getattr(result, "usage", None)
    if not callable(usage_fn):
        return 0, 0
    try:
        usage = usage_fn()
    except Exception:  # noqa: BLE001
        return 0, 0
    tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
    return tokens_in, tokens_out


async def run_agent(name: str) -> RunResult:
    """Run the registered agent `name`, write outputs, return a RunResult.

    Reads `INPUT_*` env vars + `$RUNNER_TEMP/factory/` artifacts. Writes
    `agent`, `tokens_in`, `tokens_out`, `cost_usd`, `iteration`, and
    `feedback_used` to `$GITHUB_OUTPUT`.

    Raises:
        AgentNotFoundError: If `name` is not registered.
        MissingArtifactError: If the agent declares a required artifact
            that is not present (raised by per-agent code in Spec 3).
    """
    inputs = read_action_inputs()
    iteration = int(inputs.get("iteration", "1"))
    store = ArtifactStore.from_env()
    feedback = load_feedback(store, iteration=iteration)
    agent = agent_registry.get(name)

    prompt = _compose_prompt(inputs, feedback)
    result = await agent.run(prompt)

    text = _extract_text(result)
    scan = default_output_guard.scan(text)
    if scan.sanitised_output is not None:
        text = scan.sanitised_output

    tokens_in, tokens_out = _extract_usage(result)
    cost_usd = 0.0

    write_output("agent", name)
    write_output("tokens_in", tokens_in)
    write_output("tokens_out", tokens_out)
    write_output("cost_usd", f"{cost_usd:.6f}")
    write_output("iteration", iteration)
    write_output("feedback_used", feedback is not None)

    return RunResult(
        agent=name,
        outputs={"text": text},
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
