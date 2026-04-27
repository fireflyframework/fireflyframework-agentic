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

"""Pipeline context: shared data bus that flows through the DAG."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fireflyframework_agentic.memory.manager import MemoryManager


class PipelineContext:
    """Carries inputs, intermediate results, and metadata through a pipeline.

    Parameters:
        inputs: The original pipeline input (can be multimodal).
        metadata: Arbitrary key-value pairs.
        correlation_id: Unique ID for observability correlation.
        memory: Optional :class:`MemoryManager` shared across pipeline
            steps.  Steps can use it to pass conversation history to
            agents and read/write working memory between nodes.
    """

    def __init__(
        self,
        inputs: Any = None,
        *,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        memory: MemoryManager | None = None,
    ) -> None:
        self.inputs = inputs
        self.metadata: dict[str, Any] = metadata or {}
        self.correlation_id = correlation_id or uuid.uuid4().hex
        self.memory: MemoryManager | None = memory
        self._results: dict[str, Any] = {}  # node_id -> NodeResult

    def set_node_result(self, node_id: str, result: Any) -> None:
        """Store the result for a completed node."""
        self._results[node_id] = result

    def get_node_result(self, node_id: str) -> Any:
        """Retrieve the result of a completed node."""
        return self._results.get(node_id)

    def get_node_output(self, node_id: str, key: str = "output") -> Any:
        """Retrieve a specific output key from a completed node's result."""
        result = self._results.get(node_id)
        if result is None:
            return None
        # NodeResult has an .output attribute
        if key == "output" and hasattr(result, "output"):
            return result.output
        if hasattr(result, "output") and isinstance(result.output, dict):
            return result.output.get(key)
        return None

    @property
    def results(self) -> dict[str, Any]:
        """All node results collected so far."""
        return dict(self._results)

    def __repr__(self) -> str:
        return f"PipelineContext(correlation_id={self.correlation_id!r}, completed_nodes={list(self._results.keys())})"
