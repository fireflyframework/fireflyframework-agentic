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

"""Studio AI assistant agent with canvas manipulation tools.

The assistant helps users build agent pipelines visually by manipulating
a shared canvas state.  It exposes a set of tools (add_node, connect_nodes,
configure_node, remove_node, list_nodes, list_edges) that mutate an in-memory
:class:`CanvasState` and a factory function :func:`create_studio_assistant`
that wires everything into a :class:`FireflyAgent`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.tools.base import BaseTool
from fireflyframework_genai.tools.decorators import firefly_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canvas data models
# ---------------------------------------------------------------------------

_VALID_NODE_TYPES = frozenset({"agent", "tool", "reasoning", "condition"})


class CanvasNode(BaseModel):
    """A node on the Studio canvas."""

    id: str
    type: str  # "agent", "tool", "reasoning", "condition"
    label: str = ""
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    config: dict[str, Any] = Field(default_factory=dict)


class CanvasEdge(BaseModel):
    """An edge connecting two nodes."""

    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class CanvasState(BaseModel):
    """Mutable canvas state shared across tool invocations."""

    nodes: list[CanvasNode] = Field(default_factory=list)
    edges: list[CanvasEdge] = Field(default_factory=list)
    _counter: int = PrivateAttr(default=0)

    def next_id(self, prefix: str = "node") -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"


# ---------------------------------------------------------------------------
# Canvas manipulation tools
# ---------------------------------------------------------------------------


def create_canvas_tools(canvas: CanvasState) -> list[BaseTool]:
    """Create canvas manipulation tools bound to a shared canvas state.

    Each tool is defined as an inner async function decorated with
    ``@firefly_tool(..., auto_register=False)`` so that the canvas
    instance is captured via closure.

    Returns:
        A list of :class:`BaseTool` instances ready to be passed to a
        :class:`FireflyAgent`.
    """

    @firefly_tool(
        "add_node",
        description="Add a new node to the Studio canvas.",
        auto_register=False,
    )
    async def add_node(
        node_type: str,
        label: str,
        x: float = 0.0,
        y: float = 0.0,
    ) -> str:
        """Add a node of the given type to the canvas and return its info."""
        if node_type not in _VALID_NODE_TYPES:
            raise ValueError(f"Invalid node_type '{node_type}'. Must be one of: {', '.join(sorted(_VALID_NODE_TYPES))}")
        node = CanvasNode(
            id=canvas.next_id("node"),
            type=node_type,
            label=label,
            position={"x": x, "y": y},
        )
        canvas.nodes.append(node)
        return json.dumps(
            {
                "id": node.id,
                "type": node.type,
                "label": node.label,
                "position": node.position,
            }
        )

    @firefly_tool(
        "connect_nodes",
        description="Create an edge between two nodes on the canvas.",
        auto_register=False,
    )
    async def connect_nodes(
        source_id: str,
        target_id: str,
        source_handle: str | None = None,
        target_handle: str | None = None,
    ) -> str:
        """Connect two existing nodes with a directed edge."""
        if source_id == target_id:
            raise ValueError("Cannot connect a node to itself.")
        node_ids = {n.id for n in canvas.nodes}
        if source_id not in node_ids:
            raise ValueError(f"Source node '{source_id}' does not exist.")
        if target_id not in node_ids:
            raise ValueError(f"Target node '{target_id}' does not exist.")

        edge = CanvasEdge(
            id=canvas.next_id("edge"),
            source=source_id,
            target=target_id,
            source_handle=source_handle,
            target_handle=target_handle,
        )
        canvas.edges.append(edge)
        return json.dumps(
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "source_handle": edge.source_handle,
                "target_handle": edge.target_handle,
            }
        )

    @firefly_tool(
        "configure_node",
        description="Update a node's configuration by key-value pair.",
        auto_register=False,
    )
    async def configure_node(node_id: str, key: str, value: str) -> str:
        """Set a configuration key on an existing node."""
        node = next((n for n in canvas.nodes if n.id == node_id), None)
        if node is None:
            raise ValueError(f"Node '{node_id}' does not exist.")

        if key == "label":
            node.label = value
        else:
            node.config[key] = value

        return f"Node '{node_id}': set {key}={value!r}"

    @firefly_tool(
        "remove_node",
        description="Remove a node and all its connected edges from the canvas.",
        auto_register=False,
    )
    async def remove_node(node_id: str) -> str:
        """Remove a node and any edges connected to it."""
        node = next((n for n in canvas.nodes if n.id == node_id), None)
        if node is None:
            raise ValueError(f"Node '{node_id}' does not exist.")

        canvas.nodes = [n for n in canvas.nodes if n.id != node_id]
        canvas.edges = [e for e in canvas.edges if e.source != node_id and e.target != node_id]
        return f"Removed node '{node_id}' and its connected edges."

    @firefly_tool(
        "list_nodes",
        description="List all nodes currently on the canvas.",
        auto_register=False,
    )
    async def list_nodes() -> str:
        """Return a JSON array of all canvas nodes."""
        return json.dumps(
            [
                {
                    "id": n.id,
                    "type": n.type,
                    "label": n.label,
                    "position": n.position,
                    "config": n.config,
                }
                for n in canvas.nodes
            ]
        )

    @firefly_tool(
        "list_edges",
        description="List all edges currently on the canvas.",
        auto_register=False,
    )
    async def list_edges() -> str:
        """Return a JSON array of all canvas edges."""
        return json.dumps(
            [
                {
                    "id": e.id,
                    "source": e.source,
                    "target": e.target,
                    "source_handle": e.source_handle,
                    "target_handle": e.target_handle,
                }
                for e in canvas.edges
            ]
        )

    return [add_node, connect_nodes, configure_node, remove_node, list_nodes, list_edges]


# ---------------------------------------------------------------------------
# Studio assistant factory
# ---------------------------------------------------------------------------

_STUDIO_ASSISTANT_INSTRUCTIONS = """\
You are the Firefly Studio AI assistant.  You help users design, build, and
debug agent pipelines using the visual canvas.

Your capabilities:
- **Canvas manipulation**: Add, connect, configure, and remove nodes and edges
  on the visual canvas to construct agent pipelines.
- **Framework guidance**: Explain Firefly GenAI framework concepts such as
  agents, tools, reasoning patterns, memory, middleware, and pipelines.
- **Code generation**: Suggest Python code that uses the Firefly framework
  to implement the pipeline the user is designing.
- **Debugging**: Help diagnose issues in existing pipelines by inspecting
  node configurations and edge connections.

When the user asks you to build something, prefer using the canvas tools to
create and wire up nodes rather than just describing the steps.  Always
confirm changes by listing the current canvas state when appropriate.
Keep answers concise and actionable.
"""


def create_studio_assistant(canvas: CanvasState | None = None) -> FireflyAgent:
    """Create the Studio AI assistant agent.

    Parameters:
        canvas: An optional :class:`CanvasState` instance.  When *None*, a
            fresh empty canvas is created automatically.

    Returns:
        A :class:`FireflyAgent` configured with canvas manipulation tools
        and studio-specific instructions.
    """
    if canvas is None:
        canvas = CanvasState()

    tools = create_canvas_tools(canvas)

    return FireflyAgent(
        "studio-assistant",
        model=None,
        instructions=_STUDIO_ASSISTANT_INSTRUCTIONS,
        tools=tools,
        auto_register=False,
        tags=["studio", "assistant"],
    )
