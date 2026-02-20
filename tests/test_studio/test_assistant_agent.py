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

"""Tests for the Studio AI assistant agent and canvas tools."""

from __future__ import annotations

import json

import pytest

from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.studio.assistant.agent import (
    CanvasState,
    create_canvas_tools,
    create_studio_assistant,
)


class TestCreateStudioAssistant:
    def test_create_studio_assistant_returns_firefly_agent(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        agent = create_studio_assistant()
        assert isinstance(agent, FireflyAgent)
        assert agent.name == "studio-assistant"
        assert "studio" in agent.tags
        assert "assistant" in agent.tags


class TestCanvasTools:
    @pytest.fixture()
    def canvas(self):
        return CanvasState()

    @pytest.fixture()
    def tools(self, canvas):
        return {t.name: t for t in create_canvas_tools(canvas)}

    # -- add_node ------------------------------------------------------------

    async def test_add_node_creates_node(self, canvas, tools):
        result = await tools["add_node"].execute(node_type="agent", label="My Agent")
        assert len(canvas.nodes) == 1
        assert canvas.nodes[0].type == "agent"
        assert canvas.nodes[0].label == "My Agent"

        data = json.loads(result)
        assert data["id"] == "node_1"
        assert data["type"] == "agent"

    async def test_add_node_rejects_invalid_type(self, canvas, tools):
        with pytest.raises(Exception, match="Invalid node_type"):
            await tools["add_node"].execute(node_type="invalid", label="Bad")

    # -- connect_nodes -------------------------------------------------------

    async def test_connect_nodes_creates_edge(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        await tools["add_node"].execute(node_type="tool", label="B")

        result = await tools["connect_nodes"].execute(source_id="node_1", target_id="node_2")
        assert len(canvas.edges) == 1
        assert canvas.edges[0].source == "node_1"
        assert canvas.edges[0].target == "node_2"

        data = json.loads(result)
        assert data["source"] == "node_1"
        assert data["target"] == "node_2"

    async def test_connect_nodes_rejects_self_loop(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        with pytest.raises(Exception, match="Cannot connect a node to itself"):
            await tools["connect_nodes"].execute(source_id="node_1", target_id="node_1")

    async def test_connect_nodes_rejects_missing_node(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        with pytest.raises(Exception, match="does not exist"):
            await tools["connect_nodes"].execute(source_id="node_1", target_id="node_999")

    # -- configure_node ------------------------------------------------------

    async def test_configure_node_updates_config(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        result = await tools["configure_node"].execute(node_id="node_1", key="model", value="openai:gpt-4o")
        assert canvas.nodes[0].config["model"] == "openai:gpt-4o"
        assert "model" in result

    async def test_configure_node_updates_label(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        await tools["configure_node"].execute(node_id="node_1", key="label", value="Renamed")
        assert canvas.nodes[0].label == "Renamed"

    async def test_configure_node_rejects_missing_node(self, canvas, tools):
        with pytest.raises(Exception, match="does not exist"):
            await tools["configure_node"].execute(node_id="node_999", key="model", value="openai:gpt-4o")

    # -- remove_node ---------------------------------------------------------

    async def test_remove_node_removes_node_and_edges(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        await tools["add_node"].execute(node_type="tool", label="B")
        await tools["connect_nodes"].execute(source_id="node_1", target_id="node_2")
        assert len(canvas.nodes) == 2
        assert len(canvas.edges) == 1

        await tools["remove_node"].execute(node_id="node_1")
        assert len(canvas.nodes) == 1
        assert canvas.nodes[0].id == "node_2"
        assert len(canvas.edges) == 0

    async def test_remove_node_rejects_missing_node(self, canvas, tools):
        with pytest.raises(Exception, match="does not exist"):
            await tools["remove_node"].execute(node_id="node_999")

    # -- list_nodes ----------------------------------------------------------

    async def test_list_nodes_returns_all_nodes(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        await tools["add_node"].execute(node_type="tool", label="B")
        await tools["add_node"].execute(node_type="reasoning", label="C")

        result = await tools["list_nodes"].execute()
        data = json.loads(result)
        assert len(data) == 3
        labels = {n["label"] for n in data}
        assert labels == {"A", "B", "C"}

    # -- list_edges ----------------------------------------------------------

    async def test_list_edges_returns_all_edges(self, canvas, tools):
        await tools["add_node"].execute(node_type="agent", label="A")
        await tools["add_node"].execute(node_type="tool", label="B")
        await tools["add_node"].execute(node_type="condition", label="C")
        await tools["connect_nodes"].execute(source_id="node_1", target_id="node_2")
        await tools["connect_nodes"].execute(source_id="node_2", target_id="node_3")

        result = await tools["list_edges"].execute()
        data = json.loads(result)
        assert len(data) == 2
        sources = {e["source"] for e in data}
        assert sources == {"node_1", "node_2"}
