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

"""Studio event handler for collecting pipeline execution events.

:class:`StudioEventHandler` implements the :class:`PipelineEventHandler`
protocol and collects events into a queue that can be drained and sent
over a WebSocket connection to the Studio frontend.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque


class StudioEventHandler:
    """Collects pipeline execution events for real-time Studio streaming.

    Implements the :class:`~fireflyframework_genai.pipeline.engine.PipelineEventHandler`
    protocol. Events are stored in an internal :class:`collections.deque` and
    can be drained via :meth:`drain_events` for transmission over WebSocket.

    An :class:`asyncio.Event` is used to allow consumers to efficiently wait
    for new events via :meth:`wait_for_event`.
    """

    def __init__(self) -> None:
        self._events: deque[dict] = deque()
        self._notify: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # PipelineEventHandler protocol methods
    # ------------------------------------------------------------------

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        """Called when a node begins execution."""
        self._push_event(
            {
                "type": "node_start",
                "node_id": node_id,
                "pipeline_name": pipeline_name,
            }
        )

    async def on_node_complete(self, node_id: str, pipeline_name: str, latency_ms: float) -> None:
        """Called when a node completes successfully."""
        self._push_event(
            {
                "type": "node_complete",
                "node_id": node_id,
                "pipeline_name": pipeline_name,
                "latency_ms": latency_ms,
            }
        )

    async def on_node_error(self, node_id: str, pipeline_name: str, error: str) -> None:
        """Called when a node fails (after all retries exhausted)."""
        self._push_event(
            {
                "type": "node_error",
                "node_id": node_id,
                "pipeline_name": pipeline_name,
                "error": error,
            }
        )

    async def on_node_skip(self, node_id: str, pipeline_name: str, reason: str) -> None:
        """Called when a node is skipped."""
        self._push_event(
            {
                "type": "node_skip",
                "node_id": node_id,
                "pipeline_name": pipeline_name,
                "reason": reason,
            }
        )

    async def on_pipeline_complete(self, pipeline_name: str, success: bool, duration_ms: float) -> None:
        """Called when the entire pipeline finishes."""
        self._push_event(
            {
                "type": "pipeline_complete",
                "pipeline_name": pipeline_name,
                "success": success,
                "duration_ms": duration_ms,
            }
        )

    # ------------------------------------------------------------------
    # Studio-specific methods
    # ------------------------------------------------------------------

    def drain_events(self) -> list[dict]:
        """Return all queued events and clear the internal queue.

        Returns:
            A list of event dicts in the order they were received.
            An empty list if no events are pending.
        """
        events = list(self._events)
        self._events.clear()
        self._notify.clear()
        return events

    async def wait_for_event(self, timeout: float = 5.0) -> None:
        """Block until at least one event is available or *timeout* expires.

        Parameters:
            timeout: Maximum seconds to wait. Defaults to ``5.0``.
        """
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._notify.wait(), timeout=timeout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _push_event(self, event: dict) -> None:
        """Append an event to the queue and notify any waiters."""
        self._events.append(event)
        self._notify.set()
