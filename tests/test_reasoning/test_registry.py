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

"""Tests for reasoning registry."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.reasoning.registry import ReasoningPatternRegistry


class TestReasoningPatternRegistry:
    def test_register_and_get(self):
        registry = ReasoningPatternRegistry()
        registry.register("test", object)
        assert registry.get("test") is object

    def test_get_nonexistent_raises(self):
        from fireflyframework_agentic.exceptions import ReasoningPatternNotFoundError

        registry = ReasoningPatternRegistry()
        with pytest.raises(ReasoningPatternNotFoundError):
            registry.get("nonexistent")

    def test_list_patterns(self):
        registry = ReasoningPatternRegistry()
        registry.register("a", object)
        assert "a" in registry.list_patterns()

    def test_has(self):
        registry = ReasoningPatternRegistry()
        assert registry.has("x") is False
        registry.register("x", "val")
        assert registry.has("x") is True

    def test_clear(self):
        registry = ReasoningPatternRegistry()
        registry.register("a", 1)
        registry.register("b", 2)
        assert len(registry) == 2
        registry.clear()
        assert len(registry) == 0

    def test_len(self):
        registry = ReasoningPatternRegistry()
        assert len(registry) == 0
        registry.register("a", 1)
        assert len(registry) == 1
