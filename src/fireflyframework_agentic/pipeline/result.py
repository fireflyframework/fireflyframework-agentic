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

"""Pipeline result models: per-node and aggregate pipeline outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.observability.usage import UsageSummary


class NodeResult(BaseModel):
    """Result of executing a single DAG node.

    Attributes:
        node_id: The node that produced this result.
        output: The node's output value.
        success: Whether execution succeeded.
        error: Error message if execution failed.
        latency_ms: Execution time in milliseconds.
        retries: Number of retries that were needed.
        skipped: Whether the node was skipped due to a condition gate.
        usage: Token usage summary for this node (when cost tracking is active).
    """

    node_id: str
    output: Any = None
    success: bool = True
    error: str | None = None
    latency_ms: float = 0.0
    retries: int = 0
    skipped: bool = False
    usage: UsageSummary | None = None


class ExecutionTraceEntry(BaseModel):
    """A single entry in the pipeline execution trace."""

    node_id: str
    started_at: datetime
    completed_at: datetime
    status: str  # "success", "failed", "skipped"


class PipelineResult(BaseModel):
    """Aggregate result of an entire pipeline execution.

    Attributes:
        pipeline_name: Name of the pipeline.
        outputs: Dict mapping node_id -> NodeResult for all nodes.
        final_output: The output(s) of the terminal node(s).
        execution_trace: Ordered list of execution events.
        total_duration_ms: End-to-end pipeline execution time.
        success: Whether all nodes completed successfully.
        usage: Aggregated token usage across all pipeline nodes.
    """

    pipeline_name: str = ""
    outputs: dict[str, NodeResult] = Field(default_factory=dict)
    final_output: Any = None
    execution_trace: list[ExecutionTraceEntry] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    success: bool = True
    usage: UsageSummary | None = None

    @property
    def failed_nodes(self) -> list[str]:
        return [nid for nid, r in self.outputs.items() if not r.success and not r.skipped]
