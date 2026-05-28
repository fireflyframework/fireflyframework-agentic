# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Stub agents for the software factory example.

No LLM calls. Each agent is a plain ``async (state) -> dict`` function that
returns the fields it wants merged into shared state. The behaviour is
deterministic so the example runs offline and the test suite is stable.

Two failure modes are simulated to show how state mode handles each:

* ``builder`` raises on its very first call (transient failure → recovered
  via checkpoint + ``invoke(run_id=...)`` resume).
* ``qa`` returns ``qa_status='fail'`` on iteration 1 (substantive failure →
  recovered via cycle back to ``codegen``).
"""

from __future__ import annotations

from examples.software_factory.state import BuildState

_BUILDER_ATTEMPTS: dict[str, int] = {}


async def architect(state: BuildState) -> dict:
    adr = (
        f"ADR for '{state.request}': split into api / domain / data modules; "
        "use idiomatic Firefly patterns; PSD2 strong-auth required for payments."
    )
    return {"adr": adr}


async def codegen(state: BuildState) -> dict:
    next_iteration = state.iteration + 1
    if state.qa_feedback:
        addressed = "; ".join(state.qa_feedback)
        code = f"v{next_iteration} (addresses: {addressed})"
    else:
        code = f"v{next_iteration}"
    return {"iteration": next_iteration, "code": code}


async def builder(state: BuildState) -> dict:
    # Transient failure on the very first call across the whole process —
    # exercises checkpoint + resume. Subsequent calls always succeed.
    key = "global"
    _BUILDER_ATTEMPTS[key] = _BUILDER_ATTEMPTS.get(key, 0) + 1
    if _BUILDER_ATTEMPTS[key] == 1:
        raise RuntimeError("dep install timed out")
    return {"build_status": "ok"}


async def qa(state: BuildState) -> dict:
    # Substantive failure on iteration 1: code lacks PSD2 strong-auth flow.
    # Iteration 2's codegen sees `qa_feedback` and rewrites the code,
    # so QA passes on the next visit.
    if state.iteration <= 1:
        return {
            "qa_status": "fail",
            "qa_feedback": ["missing PSD2 strong-auth flow"],
        }
    return {"qa_status": "pass"}


async def stable_release(state: BuildState) -> dict:
    return {"release_tag": "v2026.05.28"}
