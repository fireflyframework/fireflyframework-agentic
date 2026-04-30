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

"""Tests for QoS guards."""

from fireflyframework_agentic.validation.qos import GroundingChecker, QoSGuard


class TestGroundingChecker:
    def test_fully_grounded(self):
        checker = GroundingChecker()
        score, grounded = checker.check(
            "The invoice total is $500.00 from Acme Corp",
            {"total": "$500.00", "vendor": "Acme Corp"},
        )
        assert score == 1.0
        assert all(grounded.values())

    def test_partially_grounded(self):
        checker = GroundingChecker()
        score, grounded = checker.check(
            "The invoice total is $500.00",
            {"total": "$500.00", "vendor": "Nonexistent LLC"},
        )
        assert score == 0.5
        assert grounded["total"] is True
        assert grounded["vendor"] is False

    def test_none_values_trivially_grounded(self):
        checker = GroundingChecker()
        score, grounded = checker.check("some text", {"field": None})
        assert score == 1.0
        assert grounded["field"] is True

    def test_empty_fields(self):
        checker = GroundingChecker()
        score, grounded = checker.check("some text", {})
        assert score == 1.0

    def test_case_insensitive(self):
        checker = GroundingChecker(case_sensitive=False)
        score, grounded = checker.check(
            "ACME CORP invoice",
            {"vendor": "acme corp"},
        )
        assert score == 1.0


class TestQoSGuard:
    async def test_grounding_only(self):
        checker = GroundingChecker()
        guard = QoSGuard(grounding_checker=checker, min_grounding=0.8)
        result = await guard.evaluate(
            "some output",
            source_text="Invoice from Acme Corp for $100",
            extracted_fields={"vendor": "Acme Corp", "amount": "$100"},
        )
        assert result.passed is True
        assert result.grounding_score == 1.0

    async def test_grounding_fails(self):
        checker = GroundingChecker()
        guard = QoSGuard(grounding_checker=checker, min_grounding=0.9)
        result = await guard.evaluate(
            "some output",
            source_text="Invoice from Acme Corp",
            extracted_fields={"vendor": "Acme Corp", "phantom": "hallucinated"},
        )
        assert result.passed is False
        assert "grounding_failed" in result.details

    async def test_no_checks_configured(self):
        guard = QoSGuard()
        result = await guard.evaluate("some output")
        assert result.passed is True
