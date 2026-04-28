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

"""Tests for prompt templates."""

from __future__ import annotations

from fireflyframework_agentic.prompts.template import PromptTemplate


class TestPromptTemplate:
    def test_render_simple(self):
        template = PromptTemplate(
            name="greet",
            template_str="Hello, {{ name }}!",
            version="1.0.0",
        )
        assert template.render(name="Alice") == "Hello, Alice!"

    def test_render_multiple_vars(self):
        template = PromptTemplate(
            name="intro",
            template_str="{{ name }} is a {{ role }}.",
            version="1.0.0",
        )
        result = template.render(name="Bob", role="developer")
        assert result == "Bob is a developer."

    def test_template_name_and_version(self):
        template = PromptTemplate(name="t", template_str="x", version="2.0.0")
        assert template.name == "t"
        assert template.version == "2.0.0"
