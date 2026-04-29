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

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Document:
    """Result of loading a single source file: markdown content + metadata."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MarkitdownLoader:
    """Wraps `markitdown.MarkItDown` to produce a uniform Document.

    Lazily imports markitdown so the optional dep is only required when used.
    """

    def __init__(self) -> None:
        self._md: Any = None

    def _md_instance(self) -> Any:
        if self._md is None:
            from markitdown import MarkItDown
            self._md = MarkItDown()
        return self._md

    def load(self, path: str | Path) -> Document:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Source file not found: {p}")
        result = self._md_instance().convert(str(p))
        mime, _ = mimetypes.guess_type(str(p))
        return Document(
            content=result.text_content or "",
            metadata={
                "source_path": str(p.resolve()),
                "mime_type": mime or "application/octet-stream",
                "title": getattr(result, "title", None) or "",
            },
        )
