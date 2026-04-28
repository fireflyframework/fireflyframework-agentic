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

"""Structured output validation: field-level rules and composite validators.

Use :class:`FieldValidator` to validate individual fields and
:class:`OutputValidator` to validate an entire Pydantic model output with
cross-field rules.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Rule result & report models
# ---------------------------------------------------------------------------


class ValidationRuleResult(BaseModel):
    """Outcome of a single validation rule."""

    rule_name: str
    field_name: str
    passed: bool
    message: str = ""
    value: Any = None


class ValidationReport(BaseModel):
    """Aggregated validation report for an entire output."""

    valid: bool
    results: list[ValidationRuleResult] = Field(default_factory=list)
    error_count: int = 0
    field_count: int = 0

    @property
    def errors(self) -> list[ValidationRuleResult]:
        return [r for r in self.results if not r.passed]


# ---------------------------------------------------------------------------
# Validation rule protocol and implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class ValidationRule(Protocol):
    """Protocol for a single validation rule."""

    @property
    def name(self) -> str: ...

    def validate(self, value: Any) -> ValidationRuleResult: ...


class RegexRule:
    """Field must match a regex pattern.

    Parameters:
        field_name: Name of the field being validated.
        pattern: Regular expression pattern.
        description: Human-readable description of what the pattern enforces.
    """

    def __init__(self, field_name: str, pattern: str, *, description: str = "") -> None:
        self._field_name = field_name
        self._pattern = re.compile(pattern)
        self._description = description or f"Must match pattern: {pattern}"

    @property
    def name(self) -> str:
        return f"regex:{self._field_name}"

    def validate(self, value: Any) -> ValidationRuleResult:
        str_val = str(value) if value is not None else ""
        passed = bool(self._pattern.fullmatch(str_val))
        return ValidationRuleResult(
            rule_name=self.name,
            field_name=self._field_name,
            passed=passed,
            message="" if passed else self._description,
            value=value,
        )


class FormatRule:
    """Field must match a named format: email, date, phone, url, etc.

    Parameters:
        field_name: Name of the field being validated.
        format_type: One of ``"email"``, ``"date"``, ``"phone"``, ``"url"``,
            ``"iso_date"``, ``"uuid"``.
    """

    _PATTERNS: dict[str, str] = {
        "email": r"[^@\s]+@[^@\s]+\.[^@\s]+",
        "date": r"\d{4}-\d{2}-\d{2}",
        "iso_date": r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?",
        "phone": r"\+?[\d\s\-().]{7,20}",
        "url": r"https?://\S+",
        "uuid": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    }

    def __init__(self, field_name: str, format_type: str) -> None:
        if format_type not in self._PATTERNS:
            raise ValueError(f"Unknown format type '{format_type}'. Available: {list(self._PATTERNS)}")
        self._field_name = field_name
        self._format_type = format_type
        self._regex = re.compile(self._PATTERNS[format_type])

    @property
    def name(self) -> str:
        return f"format:{self._field_name}:{self._format_type}"

    def validate(self, value: Any) -> ValidationRuleResult:
        str_val = str(value) if value is not None else ""
        passed = bool(self._regex.fullmatch(str_val))
        return ValidationRuleResult(
            rule_name=self.name,
            field_name=self._field_name,
            passed=passed,
            message="" if passed else f"Value does not match {self._format_type} format",
            value=value,
        )


class RangeRule:
    """Numeric field must fall within [min_value, max_value].

    Parameters:
        field_name: Name of the field being validated.
        min_value: Minimum allowed value (inclusive). ``None`` for no lower bound.
        max_value: Maximum allowed value (inclusive). ``None`` for no upper bound.
    """

    def __init__(
        self,
        field_name: str,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> None:
        self._field_name = field_name
        self._min = min_value
        self._max = max_value

    @property
    def name(self) -> str:
        return f"range:{self._field_name}"

    def validate(self, value: Any) -> ValidationRuleResult:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return ValidationRuleResult(
                rule_name=self.name,
                field_name=self._field_name,
                passed=False,
                message="Value is not numeric",
                value=value,
            )
        if self._min is not None and num < self._min:
            return ValidationRuleResult(
                rule_name=self.name,
                field_name=self._field_name,
                passed=False,
                message=f"Value {num} below minimum {self._min}",
                value=value,
            )
        if self._max is not None and num > self._max:
            return ValidationRuleResult(
                rule_name=self.name,
                field_name=self._field_name,
                passed=False,
                message=f"Value {num} above maximum {self._max}",
                value=value,
            )
        return ValidationRuleResult(
            rule_name=self.name,
            field_name=self._field_name,
            passed=True,
            value=value,
        )


class EnumRule:
    """Field value must be in an allowed set.

    Parameters:
        field_name: Name of the field being validated.
        allowed: Sequence of allowed values.
        case_sensitive: Whether comparison is case-sensitive (default True).
    """

    def __init__(
        self,
        field_name: str,
        allowed: Sequence[str],
        *,
        case_sensitive: bool = True,
    ) -> None:
        self._field_name = field_name
        self._allowed = list(allowed)
        self._case_sensitive = case_sensitive

    @property
    def name(self) -> str:
        return f"enum:{self._field_name}"

    def validate(self, value: Any) -> ValidationRuleResult:
        str_val = str(value) if value is not None else ""
        if self._case_sensitive:
            passed = str_val in self._allowed
        else:
            passed = str_val.lower() in [a.lower() for a in self._allowed]
        return ValidationRuleResult(
            rule_name=self.name,
            field_name=self._field_name,
            passed=passed,
            message="" if passed else f"Value '{str_val}' not in allowed set: {self._allowed}",
            value=value,
        )


class CustomRule:
    """User-supplied callable that validates a field value.

    Parameters:
        field_name: Name of the field being validated.
        check_fn: Callable ``(value) -> bool``.
        description: Error message when the check fails.
    """

    def __init__(
        self,
        field_name: str,
        check_fn: Callable[[Any], bool],
        *,
        description: str = "Custom validation failed",
    ) -> None:
        self._field_name = field_name
        self._check_fn = check_fn
        self._description = description

    @property
    def name(self) -> str:
        return f"custom:{self._field_name}"

    def validate(self, value: Any) -> ValidationRuleResult:
        passed = self._check_fn(value)
        return ValidationRuleResult(
            rule_name=self.name,
            field_name=self._field_name,
            passed=passed,
            message="" if passed else self._description,
            value=value,
        )


# ---------------------------------------------------------------------------
# FieldValidator
# ---------------------------------------------------------------------------


class FieldValidator:
    """Validate a single field against one or more rules.

    Parameters:
        field_name: Name of the field to validate.
        rules: Sequence of :class:`ValidationRule` instances.
    """

    def __init__(self, field_name: str, rules: Sequence[ValidationRule]) -> None:
        self._field_name = field_name
        self._rules = list(rules)

    def validate(self, value: Any) -> list[ValidationRuleResult]:
        """Run all rules against *value* and return results."""
        return [rule.validate(value) for rule in self._rules]


# ---------------------------------------------------------------------------
# OutputValidator
# ---------------------------------------------------------------------------


class OutputValidator:
    """Validate an entire structured output (dict or Pydantic model).

    Parameters:
        field_validators: Mapping of field name -> list of rules.
        cross_field_rules: Optional list of callables that receive the full
            output dict and return a :class:`ValidationRuleResult`.
    """

    def __init__(
        self,
        field_validators: dict[str, Sequence[ValidationRule]] | None = None,
        *,
        cross_field_rules: Sequence[Callable[[dict[str, Any]], ValidationRuleResult]] | None = None,
    ) -> None:
        self._field_validators: dict[str, list[ValidationRule]] = {
            k: list(v) for k, v in (field_validators or {}).items()
        }
        self._cross_field_rules = list(cross_field_rules or [])

    def add_field_rule(self, field_name: str, rule: ValidationRule) -> None:
        """Add a rule for a specific field."""
        self._field_validators.setdefault(field_name, []).append(rule)

    def validate(self, output: Any) -> ValidationReport:
        """Validate *output* and return a :class:`ValidationReport`.

        *output* can be a dict, a Pydantic BaseModel, or any object whose
        fields can be accessed via attribute or key lookup.
        """
        data = self._to_dict(output)
        results: list[ValidationRuleResult] = []

        for field_name, rules in self._field_validators.items():
            value = data.get(field_name)
            for rule in rules:
                results.append(rule.validate(value))

        for cross_rule in self._cross_field_rules:
            results.append(cross_rule(data))

        error_count = sum(1 for r in results if not r.passed)
        return ValidationReport(
            valid=error_count == 0,
            results=results,
            error_count=error_count,
            field_count=len(self._field_validators),
        )

    @staticmethod
    def _to_dict(output: Any) -> dict[str, Any]:
        if isinstance(output, dict):
            return output
        if isinstance(output, BaseModel):
            return output.model_dump()
        # Fallback: try __dict__
        return getattr(output, "__dict__", {})
