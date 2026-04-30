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

"""Output validation and QoS guards for structured extraction results.

This package provides field-level validation rules, composite output
validators, and quality-of-service guards for hallucination detection.
"""

from fireflyframework_agentic.validation.qos import (
    ConfidenceScorer,
    ConsistencyChecker,
    GroundingChecker,
    QoSGuard,
    QoSResult,
)
from fireflyframework_agentic.validation.reviewer import (
    OutputReviewer,
    RetryAttempt,
    ReviewResult,
)
from fireflyframework_agentic.validation.rules import (
    CustomRule,
    EnumRule,
    FieldValidator,
    FormatRule,
    OutputValidator,
    RangeRule,
    RegexRule,
    ValidationReport,
    ValidationRule,
    ValidationRuleResult,
)

__all__ = [
    "ConfidenceScorer",
    "ConsistencyChecker",
    "CustomRule",
    "EnumRule",
    "FieldValidator",
    "FormatRule",
    "GroundingChecker",
    "OutputReviewer",
    "OutputValidator",
    "QoSGuard",
    "QoSResult",
    "RangeRule",
    "RegexRule",
    "RetryAttempt",
    "ReviewResult",
    "ValidationReport",
    "ValidationRule",
    "ValidationRuleResult",
]
