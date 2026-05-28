# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Console progress handler.

Implements (structurally) the framework's :class:`StatePipelineEventHandler`
Protocol. Prints one line per pipeline / node event so the QA loop and
checkpoint+resume flow are visible when running the example by hand.
"""

from __future__ import annotations


class ProgressHandler:
    async def on_pipeline_start(self, pipeline_name: str, run_id: str) -> None:
        print(f"▶ [{pipeline_name}] run {run_id[:8]}… starting")

    async def on_node_start(self, pipeline_name: str, run_id: str, node_id: str, visit: int) -> None:
        print(f"  ▶ {node_id} (visit #{visit})")

    async def on_node_complete(self, pipeline_name: str, run_id: str, node_id: str, latency_ms: float) -> None:
        print(f"    ✔ {node_id} ({latency_ms:.0f}ms)")

    async def on_node_error(self, pipeline_name: str, run_id: str, node_id: str, error: str) -> None:
        print(f"    ✗ {node_id}: {error}")

    async def on_node_pause(self, pipeline_name: str, run_id: str, node_id: str, reason: str) -> None:
        print(f"    ⏸ {node_id}: {reason}")

    async def on_pipeline_complete(self, pipeline_name: str, run_id: str, success: bool, duration_ms: float) -> None:
        status = "OK" if success else "FAILED"
        print(f"═ [{pipeline_name}] {status} in {duration_ms:.0f}ms")
