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

"""Tests for the tool registry."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.tools.builder import ToolBuilder
from fireflyframework_agentic.tools.registry import ToolRegistry


class TestToolRegistry:
    def _make_tool(self, name: str):
        async def handler(**kw):
            return "ok"

        return ToolBuilder(name).description("d").handler(handler).build()

    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = self._make_tool("t1")
        registry.register(tool)
        assert registry.get("t1") is tool

    def test_get_nonexistent_raises(self):
        from fireflyframework_agentic.exceptions import ToolNotFoundError

        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            registry.get("nonexistent")

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(self._make_tool("a"))
        registry.register(self._make_tool("b"))
        assert len(registry.list_tools()) == 2
