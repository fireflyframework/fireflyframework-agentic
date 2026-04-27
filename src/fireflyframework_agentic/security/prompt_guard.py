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

"""Prompt injection detection and input sanitisation.

:class:`PromptGuard` scans user input for known prompt-injection patterns
and optionally sanitises suspicious content before it reaches the LLM.

Usage::

    from fireflyframework_agentic.security import default_prompt_guard

    result = default_prompt_guard.scan("Ignore all previous instructions")
    if not result.safe:
        raise ValueError(f"Blocked: {result.reason}")
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Default injection patterns — known prompt-injection phrases
_DEFAULT_PATTERNS: list[str] = [
    r"(?i)ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)",
    r"(?i)disregard\s+(all\s+)?(above|previous|prior)",
    r"(?i)forget\s+(all\s+)?(you\s+)?(know|were\s+told)",
    r"(?i)you\s+are\s+now\s+(a|an)\b",
    r"(?i)new\s+instructions?\s*:",
    r"(?i)system\s*:\s*",
    r"(?i)\bdo\s+not\s+follow\b.*\binstructions\b",
    r"(?i)\boverride\b.*\bsystem\b",
    r"(?i)pretend\s+you\s+are",
    r"(?i)act\s+as\s+if\s+you\s+are",
    # -- Encoding bypass detection --
    r"(?i)base64[_\s]*decode",
    r"(?i)\batob\s*\(",
    r"(?i)from\s+base64\s+import",
    # -- Unicode homoglyph / zero-width evasion --
    r"[\u200b\u200c\u200d\u2060\ufeff]{3,}",  # clusters of zero-width chars
    r"(?i)[\u0400-\u04ff].*ignore.*instructions",  # Cyrillic mixed with Latin
    # -- Multi-language injection patterns --
    r"(?i)(?:ignorar|ignora)\s+(?:todas?\s+)?(?:las?\s+)?instrucciones",  # Spanish
    r"(?i)(?:ignorer|ignorez)\s+(?:toutes?\s+)?(?:les?\s+)?instructions",  # French
    r"(?i)(?:ignoriere|ignorieren)\s+(?:alle\s+)?(?:vorherigen?\s+)?anweisungen",  # German
    # -- Advanced injection techniques --
    r"(?i)\bDAN\b.*\bjailbreak\b",
    r"(?i)developer\s+mode\s+(enabled|activated|on)",
    r"(?i)\benable\s+unrestricted\s+mode\b",
    r"(?i)respond\s+without\s+(?:any\s+)?(?:restrictions|filters|limitations)",
    # -- System prompt extraction attacks --
    r"(?i)(?:what|reveal|show|repeat|print|output|display)\s+(?:is\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)",
    r"(?i)repeat\s+(?:back\s+)?(?:everything|all)\s+(?:above|before|I\s+said)",
    r"(?i)(?:tell|give)\s+me\s+(?:your|the)\s+(?:original|initial|full)\s+(?:prompt|instructions)",
]


@dataclass
class PromptGuardResult:
    """Result of scanning user input for injection patterns.

    Attributes:
        safe: Whether the input passed all checks.
        reason: Human-readable explanation if *safe* is False.
        matched_patterns: List of pattern names/indices that matched.
        sanitised_input: The input with suspicious fragments removed (if sanitisation is enabled).
    """

    safe: bool = True
    reason: str = ""
    matched_patterns: list[str] = field(default_factory=list)
    sanitised_input: str | None = None


class PromptGuard:
    """Scans user prompts for prompt injection patterns.

    Parameters:
        patterns: Regex patterns that indicate injection attempts.
            Defaults to a built-in set of common patterns.
        custom_patterns: Additional patterns to append to the defaults.
        sanitise: When *True*, matched fragments are replaced with
            ``[REDACTED]`` in ``sanitised_input``.
        max_input_length: Reject inputs exceeding this length (0 = no limit).
    """

    def __init__(
        self,
        *,
        patterns: Sequence[str] | None = None,
        custom_patterns: Sequence[str] = (),
        sanitise: bool = False,
        max_input_length: int = 0,
    ) -> None:
        raw_patterns = list(patterns or _DEFAULT_PATTERNS) + list(custom_patterns)
        self._compiled = [re.compile(p) for p in raw_patterns]
        self._raw_patterns = raw_patterns
        self._sanitise = sanitise
        self._max_length = max_input_length

    def scan(self, text: str) -> PromptGuardResult:
        """Scan *text* for injection patterns.

        Returns a :class:`PromptGuardResult` describing whether the input
        is safe and which patterns (if any) matched.
        """
        if self._max_length > 0 and len(text) > self._max_length:
            return PromptGuardResult(
                safe=False,
                reason=f"Input exceeds maximum length ({len(text)} > {self._max_length})",
            )

        matched: list[str] = []
        sanitised = text

        for i, pattern in enumerate(self._compiled):
            if pattern.search(text):
                matched.append(self._raw_patterns[i])
                if self._sanitise:
                    sanitised = pattern.sub("[REDACTED]", sanitised)

        if matched:
            logger.warning(
                "Prompt injection detected: %d pattern(s) matched",
                len(matched),
            )
            return PromptGuardResult(
                safe=False,
                reason=f"Matched {len(matched)} injection pattern(s)",
                matched_patterns=matched,
                sanitised_input=sanitised if self._sanitise else None,
            )

        return PromptGuardResult(safe=True, sanitised_input=text if self._sanitise else None)


# Module-level default instance
default_prompt_guard = PromptGuard()
