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

"""Output sanitisation and data-leakage detection.

:class:`OutputGuard` scans LLM responses for PII, secrets, harmful
content, and custom deny patterns before the output reaches the caller.

Usage::

    from fireflyframework_agentic.security import OutputGuard

    guard = OutputGuard()
    result = guard.scan("The user's SSN is 123-45-6789")
    if not result.safe:
        print(f"Blocked: {result.reason}")
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# -- PII patterns -----------------------------------------------------------

_PII_PATTERNS: dict[str, str] = {
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d{4}[- ]?){3}\d{4}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone_us": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ip_address": r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
    "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b",
}

# -- Secrets patterns -------------------------------------------------------

_SECRETS_PATTERNS: dict[str, str] = {
    "api_key_generic": r"(?i)\b(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    "bearer_token": r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}",
    "openai_key": r"\bsk-[A-Za-z0-9]{20,}\b",
    "anthropic_key": r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b",
    "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
    "aws_secret_key": r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}",
    "private_key": r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----",
    "github_token": r"\bgh[ps]_[A-Za-z0-9_]{36,}\b",
    "password_in_text": r"(?i)password\s*[:=]\s*['\"]?[^\s'\"]{8,}",
}

# -- Harmful content patterns -----------------------------------------------

_HARMFUL_PATTERNS: dict[str, str] = {
    "sql_injection": r"(?i)(?:DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET).*(?:--|;)",
    "shell_injection": r"(?i)(?:rm\s+-rf\s+/|sudo\s+|chmod\s+777|curl\s+.*\|\s*(?:ba)?sh)",
    "xss_script": r"(?si)<script\b[^>]*>.*?</script>",
    "data_uri": r"data:[a-zA-Z0-9]+/[a-zA-Z0-9]+;base64,[A-Za-z0-9+/=]{100,}",
}


@dataclass
class OutputGuardResult:
    """Result of scanning an LLM output.

    Attributes:
        safe: Whether the output passed all checks.
        reason: Human-readable explanation if *safe* is False.
        matched_categories: Categories of patterns that matched (e.g. ``"pii"``, ``"secrets"``).
        matched_patterns: Specific pattern names that matched.
        sanitised_output: The output with matches redacted (if sanitisation is enabled).
        pii_detected: Whether PII patterns were found.
        secrets_detected: Whether secret/credential patterns were found.
        harmful_detected: Whether harmful content patterns were found.
    """

    safe: bool = True
    reason: str = ""
    matched_categories: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)
    sanitised_output: str | None = None
    pii_detected: bool = False
    secrets_detected: bool = False
    harmful_detected: bool = False


class OutputGuard:
    """Scans LLM output for PII, secrets, harmful content, and custom patterns.

    Parameters:
        scan_pii: Enable PII detection (SSN, credit card, email, phone, etc.).
        scan_secrets: Enable secret/credential detection (API keys, tokens, etc.).
        scan_harmful: Enable harmful content detection (SQL/shell injection, XSS).
        custom_patterns: Additional ``{name: regex}`` patterns to check.
        deny_patterns: Simple string patterns that should never appear in output.
        sanitise: When *True*, matched content is replaced with ``[REDACTED]``
            in :attr:`OutputGuardResult.sanitised_output`.
        max_output_length: Reject outputs exceeding this length (0 = no limit).
    """

    def __init__(
        self,
        *,
        scan_pii: bool = True,
        scan_secrets: bool = True,
        scan_harmful: bool = True,
        custom_patterns: dict[str, str] | None = None,
        deny_patterns: Sequence[str] = (),
        sanitise: bool = False,
        max_output_length: int = 0,
    ) -> None:
        self._sanitise = sanitise
        self._max_length = max_output_length

        # Build compiled pattern groups
        self._groups: dict[str, dict[str, re.Pattern[str]]] = {}
        if scan_pii:
            self._groups["pii"] = {k: re.compile(v) for k, v in _PII_PATTERNS.items()}
        if scan_secrets:
            self._groups["secrets"] = {k: re.compile(v) for k, v in _SECRETS_PATTERNS.items()}
        if scan_harmful:
            self._groups["harmful"] = {k: re.compile(v) for k, v in _HARMFUL_PATTERNS.items()}
        if custom_patterns:
            self._groups["custom"] = {k: re.compile(v) for k, v in custom_patterns.items()}
        if deny_patterns:
            self._groups["deny"] = {f"deny_{i}": re.compile(re.escape(p)) for i, p in enumerate(deny_patterns)}

    def scan(self, text: str) -> OutputGuardResult:
        """Scan *text* for sensitive or harmful content.

        Returns an :class:`OutputGuardResult` describing whether the output
        is safe and which patterns (if any) matched.
        """
        if self._max_length > 0 and len(text) > self._max_length:
            return OutputGuardResult(
                safe=False,
                reason=f"Output exceeds maximum length ({len(text)} > {self._max_length})",
            )

        matched_categories: list[str] = []
        matched_patterns: list[str] = []
        sanitised = text

        for category, patterns in self._groups.items():
            for name, compiled in patterns.items():
                if compiled.search(text):
                    if category not in matched_categories:
                        matched_categories.append(category)
                    matched_patterns.append(f"{category}:{name}")
                    if self._sanitise:
                        sanitised = compiled.sub("[REDACTED]", sanitised)

        if matched_patterns:
            pii_found = "pii" in matched_categories
            secrets_found = "secrets" in matched_categories
            harmful_found = "harmful" in matched_categories

            logger.warning(
                "Output guard: %d pattern(s) matched across %s",
                len(matched_patterns),
                matched_categories,
            )

            return OutputGuardResult(
                safe=False,
                reason=f"Matched {len(matched_patterns)} pattern(s) in categories: {matched_categories}",
                matched_categories=matched_categories,
                matched_patterns=matched_patterns,
                sanitised_output=sanitised if self._sanitise else None,
                pii_detected=pii_found,
                secrets_detected=secrets_found,
                harmful_detected=harmful_found,
            )

        return OutputGuardResult(
            safe=True,
            sanitised_output=text if self._sanitise else None,
        )


# Module-level default instance
default_output_guard = OutputGuard()
