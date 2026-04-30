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

import pytest

from fireflyframework_agentic.exceptions import PromptNotFoundError
from fireflyframework_agentic.prompts.registry import PromptRegistry
from fireflyframework_agentic.prompts.template import PromptTemplate


def test_register_and_get():
    registry = PromptRegistry()
    t = PromptTemplate(name="a", system_template="hi", user_template="there", version="1.0.0")
    registry.register(t)
    assert registry.get("a") is t


def test_versioned_get():
    registry = PromptRegistry()
    t1 = PromptTemplate(name="a", system_template="v1", user_template="user", version="1.0.0")
    t2 = PromptTemplate(name="a", system_template="v2", user_template="user", version="2.0.0")
    registry.register(t1)
    registry.register(t2)
    assert registry.get("a", "1.0.0") is t1
    assert registry.get("a") is t2


def test_get_unknown_name_raises():
    registry = PromptRegistry()
    with pytest.raises(PromptNotFoundError):
        registry.get("nonexistent")


def test_get_unknown_version_raises():
    registry = PromptRegistry()
    t = PromptTemplate(name="a", system_template="s", user_template="u", version="1.0.0")
    registry.register(t)
    with pytest.raises(PromptNotFoundError):
        registry.get("a", "9.9.9")


def test_has():
    registry = PromptRegistry()
    assert not registry.has("a")
    registry.register(PromptTemplate(name="a", system_template="s", user_template="u"))
    assert registry.has("a")


def test_len_and_contains():
    registry = PromptRegistry()
    assert len(registry) == 0
    assert "a" not in registry
    registry.register(PromptTemplate(name="a", system_template="s", user_template="u", version="1.0.0"))
    registry.register(PromptTemplate(name="a", system_template="s", user_template="u", version="2.0.0"))
    assert len(registry) == 2
    assert "a" in registry


def test_list_templates():
    registry = PromptRegistry()
    registry.register(PromptTemplate(name="x", system_template="s", user_template="u", version="1.0.0"))
    registry.register(PromptTemplate(name="y", system_template="s", user_template="u", version="1.0.0"))
    infos = registry.list_templates()
    names = {i.name for i in infos}
    assert names == {"x", "y"}


def test_clear():
    registry = PromptRegistry()
    registry.register(PromptTemplate(name="a", system_template="s", user_template="u"))
    registry.clear()
    assert len(registry) == 0
    assert not registry.has("a")
