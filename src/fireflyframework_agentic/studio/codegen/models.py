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

"""Graph intermediate-representation models.

These Pydantic models describe the visual graph that the Studio canvas
produces.  The frontend serialises the @xyflow/svelte node/edge data into
these structures, which the backend then lowers into executable Python code.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class NodeType(StrEnum):
    """Discriminator for the kind of behaviour a graph node represents."""

    AGENT = "agent"
    TOOL = "tool"
    REASONING = "reasoning"
    PIPELINE_STEP = "pipeline_step"
    FAN_OUT = "fan_out"
    FAN_IN = "fan_in"
    CONDITION = "condition"
    MEMORY = "memory"
    VALIDATOR = "validator"
    CUSTOM_CODE = "custom_code"
    INPUT = "input"
    OUTPUT = "output"


class GraphNode(BaseModel):
    """A single node on the visual canvas."""

    id: str
    type: NodeType
    label: str
    position: dict[str, float]  # {"x": 100, "y": 200}
    data: dict  # node-specific configuration
    width: float | None = None
    height: float | None = None


class GraphEdge(BaseModel):
    """A directed connection between two nodes."""

    id: str
    source: str
    target: str
    source_handle: str = "output"
    target_handle: str = "input"
    label: str | None = None


class GraphModel(BaseModel):
    """Top-level graph that the canvas persists and the code generator reads."""

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    metadata: dict = {}
