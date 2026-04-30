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

"""Tests for the tool builder."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.tools.builder import ToolBuilder


class TestToolBuilder:
    def test_build_tool(self):
        async def handler(**kwargs):
            return "ok"

        tool = ToolBuilder("t").description("d").handler(handler).build()
        assert tool.name == "t"
        assert tool.description == "d"

    def test_build_without_handler_raises(self):
        with pytest.raises(ValueError):
            ToolBuilder("t").description("d").build()

    def test_fluent_api_returns_self(self):
        builder = ToolBuilder("n")
        assert builder.description("d") is builder
        assert builder.tag("x") is builder
