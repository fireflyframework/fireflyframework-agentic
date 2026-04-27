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

"""Tests for prompt registry."""

from __future__ import annotations

from fireflyframework_agentic.prompts.registry import PromptRegistry
from fireflyframework_agentic.prompts.template import PromptTemplate


class TestPromptRegistry:
    def test_register_and_get(self):
        registry = PromptRegistry()
        t = PromptTemplate(name="a", template_str="hi", version="1.0.0")
        registry.register(t)
        assert registry.get("a") is t

    def test_versioned_get(self):
        registry = PromptRegistry()
        t1 = PromptTemplate(name="a", template_str="v1", version="1.0.0")
        t2 = PromptTemplate(name="a", template_str="v2", version="2.0.0")
        registry.register(t1)
        registry.register(t2)
        assert registry.get("a", "1.0.0") is t1
        assert registry.get("a") is t2
