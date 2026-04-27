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

"""Prompt validation: token limits, required sections, and format checks.

:class:`PromptValidator` inspects a rendered prompt string and reports
all detected issues via :class:`ValidationResult`.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel


class ValidationResult(BaseModel):
    """Outcome of prompt validation."""

    valid: bool
    errors: list[str] = []


class PromptValidator:
    """Validates rendered prompts against configurable constraints.

    Parameters:
        max_tokens: Maximum estimated token count (word_count / 0.75).
            Set to ``0`` to disable the limit.
        required_sections: Substrings that must appear in the rendered text.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 0,
        required_sections: Sequence[str] = (),
    ) -> None:
        self._max_tokens = max_tokens
        self._required_sections = list(required_sections)

    def validate(self, rendered: str) -> ValidationResult:
        """Validate *rendered* and return a :class:`ValidationResult`."""
        errors: list[str] = []

        # Token limit check
        if self._max_tokens > 0:
            estimated = int(len(rendered.split()) / 0.75)
            if estimated > self._max_tokens:
                errors.append(f"Estimated token count ({estimated}) exceeds limit ({self._max_tokens})")

        # Required sections check
        for section in self._required_sections:
            if section not in rendered:
                errors.append(f"Required section missing: '{section}'")

        return ValidationResult(valid=len(errors) == 0, errors=errors)
