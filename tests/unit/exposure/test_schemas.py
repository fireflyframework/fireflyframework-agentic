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

"""Tests for REST exposure schemas."""

from __future__ import annotations

from fireflyframework_agentic.exposure.rest.schemas import (
    AgentRequest,
    AgentResponse,
    HealthResponse,
)


class TestSchemas:
    def test_agent_request(self):
        req = AgentRequest(prompt="hello")
        assert req.prompt == "hello"

    def test_agent_response(self):
        resp = AgentResponse(agent_name="test", output="world")
        assert resp.agent_name == "test"
        assert resp.success is True

    def test_agent_response_failure(self):
        resp = AgentResponse(agent_name="test", output=None, success=False, error="boom")
        assert not resp.success
        assert resp.error == "boom"

    def test_health_response(self):
        h = HealthResponse(status="healthy")
        assert h.status == "healthy"
