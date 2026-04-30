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

"""Tests for the audit trail."""

from __future__ import annotations

from fireflyframework_agentic.explainability.audit import AuditTrail


class TestAuditTrail:
    def test_append(self):
        trail = AuditTrail()
        entry = trail.append(actor="agent_a", action="tool_execution", resource="search")
        assert entry.actor == "agent_a"
        assert len(trail) == 1

    def test_export_json(self):
        trail = AuditTrail()
        trail.append(actor="a", action="llm_call")
        json_str = trail.export_json()
        assert "llm_call" in json_str

    def test_entries_returns_copy(self):
        trail = AuditTrail()
        trail.append(actor="a", action="act")
        entries = trail.entries
        assert len(entries) == 1
