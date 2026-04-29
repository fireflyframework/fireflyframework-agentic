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

"""Tests for validation rules and output validator."""

import pytest
from pydantic import BaseModel

from fireflyframework_agentic.validation.rules import (
    CustomRule,
    EnumRule,
    FieldValidator,
    FormatRule,
    OutputValidator,
    RangeRule,
    RegexRule,
    ValidationRuleResult,
)


class TestRegexRule:
    def test_match(self):
        rule = RegexRule("zip", r"\d{5}")
        result = rule.validate("12345")
        assert result.passed is True

    def test_no_match(self):
        rule = RegexRule("zip", r"\d{5}")
        result = rule.validate("abc")
        assert result.passed is False
        assert result.message

    def test_none_value(self):
        rule = RegexRule("zip", r"\d{5}")
        result = rule.validate(None)
        assert result.passed is False


class TestFormatRule:
    def test_email_valid(self):
        rule = FormatRule("email", "email")
        assert rule.validate("user@example.com").passed is True

    def test_email_invalid(self):
        rule = FormatRule("email", "email")
        assert rule.validate("not-an-email").passed is False

    def test_date_valid(self):
        rule = FormatRule("date", "date")
        assert rule.validate("2026-01-15").passed is True

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="Unknown format type"):
            FormatRule("field", "nonexistent")


class TestRangeRule:
    def test_within_range(self):
        rule = RangeRule("age", min_value=0, max_value=120)
        assert rule.validate(25).passed is True

    def test_below_min(self):
        rule = RangeRule("age", min_value=0)
        assert rule.validate(-1).passed is False

    def test_above_max(self):
        rule = RangeRule("age", max_value=120)
        assert rule.validate(150).passed is False

    def test_non_numeric(self):
        rule = RangeRule("age", min_value=0)
        assert rule.validate("abc").passed is False


class TestEnumRule:
    def test_valid_value(self):
        rule = EnumRule("status", ["active", "inactive"])
        assert rule.validate("active").passed is True

    def test_invalid_value(self):
        rule = EnumRule("status", ["active", "inactive"])
        assert rule.validate("deleted").passed is False

    def test_case_insensitive(self):
        rule = EnumRule("status", ["Active"], case_sensitive=False)
        assert rule.validate("active").passed is True


class TestCustomRule:
    def test_passes(self):
        rule = CustomRule("name", lambda v: len(str(v)) > 2, description="Too short")
        assert rule.validate("John").passed is True

    def test_fails(self):
        rule = CustomRule("name", lambda v: len(str(v)) > 2, description="Too short")
        result = rule.validate("A")
        assert result.passed is False
        assert result.message == "Too short"


class TestFieldValidator:
    def test_multiple_rules(self):
        fv = FieldValidator(
            "amount",
            [
                RangeRule("amount", min_value=0, max_value=10000),
                CustomRule("amount", lambda v: v != 0, description="Cannot be zero"),
            ],
        )
        results = fv.validate(500)
        assert all(r.passed for r in results)


class TestOutputValidator:
    def test_dict_validation(self):
        validator = OutputValidator(
            {
                "email": [FormatRule("email", "email")],
                "age": [RangeRule("age", min_value=0, max_value=120)],
            }
        )
        report = validator.validate({"email": "a@b.com", "age": 30})
        assert report.valid is True
        assert report.error_count == 0

    def test_pydantic_model_validation(self):
        class Invoice(BaseModel):
            total: float
            currency: str

        validator = OutputValidator(
            {
                "total": [RangeRule("total", min_value=0)],
                "currency": [EnumRule("currency", ["USD", "EUR", "GBP"])],
            }
        )
        report = validator.validate(Invoice(total=100.0, currency="USD"))
        assert report.valid is True

    def test_validation_failure(self):
        validator = OutputValidator(
            {
                "email": [FormatRule("email", "email")],
            }
        )
        report = validator.validate({"email": "not-email"})
        assert report.valid is False
        assert report.error_count == 1
        assert len(report.errors) == 1

    def test_cross_field_rule(self):
        def check_total(data: dict) -> ValidationRuleResult:
            passed = data.get("subtotal", 0) <= data.get("total", 0)
            return ValidationRuleResult(
                rule_name="cross:subtotal_le_total",
                field_name="total",
                passed=passed,
                message="" if passed else "Subtotal exceeds total",
            )

        validator = OutputValidator(cross_field_rules=[check_total])
        report = validator.validate({"subtotal": 50, "total": 100})
        assert report.valid is True

    def test_add_field_rule(self):
        validator = OutputValidator()
        validator.add_field_rule("name", RegexRule("name", r".{2,}"))
        report = validator.validate({"name": "Jo"})
        assert report.valid is True
