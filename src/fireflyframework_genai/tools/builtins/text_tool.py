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

"""Built-in text utility tool.

Provides common text operations that agents frequently need: counting,
extraction, and truncation.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

from fireflyframework_genai.tools.base import BaseTool, GuardProtocol, ParameterSpec


class TextTool(BaseTool):
    """Common text operations for agents.

    Supported actions:

    * ``"count"`` -- count words, characters, sentences, or lines.
    * ``"extract"`` -- extract all matches for a regex pattern.
    * ``"truncate"`` -- truncate text to a maximum word count.
    * ``"replace"`` -- regex-based find-and-replace.
    * ``"split"`` -- split text by a separator pattern.

    Parameters:
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "text",
            description="Text utilities: count, extract, truncate, replace, and split",
            tags=["text", "utility"],
            guards=guards,
            parameters=[
                ParameterSpec(
                    name="action",
                    type_annotation="str",
                    description="One of: count, extract, truncate, replace, split",
                    required=True,
                ),
                ParameterSpec(
                    name="text",
                    type_annotation="str",
                    description="Input text to operate on",
                    required=True,
                ),
                ParameterSpec(
                    name="pattern",
                    type_annotation="str | None",
                    description="Regex pattern (for extract, replace, split)",
                    required=False,
                    default=None,
                ),
                ParameterSpec(
                    name="replacement",
                    type_annotation="str | None",
                    description="Replacement string (for replace action)",
                    required=False,
                    default=None,
                ),
                ParameterSpec(
                    name="max_words",
                    type_annotation="int | None",
                    description="Maximum word count (for truncate action)",
                    required=False,
                    default=None,
                ),
                ParameterSpec(
                    name="unit",
                    type_annotation="str",
                    description="Count unit: words, chars, sentences, or lines",
                    required=False,
                    default="words",
                ),
            ],
        )

    async def _execute(self, **kwargs: Any) -> Any:
        action: str = kwargs["action"]
        text: str = kwargs["text"]

        if action == "count":
            return self._count(text, kwargs.get("unit", "words"))
        if action == "extract":
            pattern = kwargs.get("pattern")
            if not pattern:
                raise ValueError("'pattern' is required for the extract action")
            return await self._extract(text, pattern)
        if action == "truncate":
            max_words = kwargs.get("max_words")
            if max_words is None:
                raise ValueError("'max_words' is required for the truncate action")
            return self._truncate(text, int(max_words))
        if action == "replace":
            pattern = kwargs.get("pattern")
            replacement = kwargs.get("replacement", "")
            if not pattern:
                raise ValueError("'pattern' is required for the replace action")
            return await self._replace(text, pattern, replacement or "")
        if action == "split":
            pattern = kwargs.get("pattern", r"\n")
            return await self._split(text, pattern or r"\n")

        raise ValueError(f"Unknown action '{action}'; expected count, extract, truncate, replace, or split")

    @staticmethod
    def _count(text: str, unit: str) -> dict[str, int]:
        """Count text units."""
        if unit == "words":
            return {"words": len(text.split())}
        if unit == "chars":
            return {"chars": len(text)}
        if unit == "sentences":
            sentences = re.split(r"(?<=[.!?])\s+", text.strip())
            return {"sentences": len(sentences) if text.strip() else 0}
        if unit == "lines":
            return {"lines": len(text.splitlines())}
        raise ValueError(f"Unknown unit '{unit}'; expected words, chars, sentences, or lines")

    @staticmethod
    async def _extract(text: str, pattern: str) -> list[str]:
        """Extract all regex matches with timeout protection."""
        return await asyncio.wait_for(asyncio.to_thread(re.findall, pattern, text), timeout=5.0)

    @staticmethod
    def _truncate(text: str, max_words: int) -> str:
        """Truncate to max_words, appending '...' if truncated."""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + "..."

    @staticmethod
    async def _replace(text: str, pattern: str, replacement: str) -> str:
        """Regex-based find-and-replace with timeout protection."""
        return await asyncio.wait_for(asyncio.to_thread(re.sub, pattern, replacement, text), timeout=5.0)

    @staticmethod
    async def _split(text: str, pattern: str) -> list[str]:
        """Split text by a regex pattern with timeout protection."""
        return await asyncio.wait_for(asyncio.to_thread(re.split, pattern, text), timeout=5.0)
