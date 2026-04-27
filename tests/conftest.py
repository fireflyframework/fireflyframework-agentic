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

"""Shared test fixtures for the fireflyframework-agentic test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_registries():
    """Reset global registries between tests to avoid cross-test contamination."""
    from fireflyframework_agentic.agents.registry import agent_registry
    from fireflyframework_agentic.reasoning.registry import reasoning_registry
    from fireflyframework_agentic.tools.registry import tool_registry

    agent_registry._agents.clear()
    tool_registry.clear()
    reasoning_registry.clear()
    yield
    agent_registry._agents.clear()
    tool_registry.clear()
    reasoning_registry.clear()
