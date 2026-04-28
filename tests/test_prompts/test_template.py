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

from pathlib import Path

import pytest
import yaml

from fireflyframework_agentic import PromptError
from fireflyframework_agentic.prompts.template import Prompt, PromptTemplate


@pytest.fixture
def prompt():
    path = Path(__file__).parent / "assets" / "valid" / "valid.yaml.j2"
    with open(path) as f:
        return yaml.safe_load(f)


def test_new_prompt_template(prompt):
    template = PromptTemplate(**prompt)

    assert template.name == "TestTemplate"
    assert template.version == "1.0.0"
    assert template.description == "A test template"
    assert "You are a helpful assistant" in template.system_template
    assert "{{ query }}" in template.user_template
    assert template.required_variables == ["query"]
    assert template.metadata == {"category": "test"}


def test_prompt_template_render(prompt):
    template = PromptTemplate(**prompt)
    result = template.render(query="What is the weather?")

    assert isinstance(result, Prompt)
    assert result.system is not None
    assert result.user is not None
    assert "You are a helpful assistant" in result.system
    assert "What is the weather?" in result.user


def test_prompt_template_render_missing_variables(prompt):
    template = PromptTemplate(**prompt)

    with pytest.raises(PromptError, match="Template 'TestTemplate' is missing required variables: query"):
        template.render()
