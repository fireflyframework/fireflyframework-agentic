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

"""Built-in filesystem tool for reading, writing, and listing files.

Operations are restricted to a configurable *base_dir* to prevent
path-traversal attacks.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fireflyframework_genai.tools.base import BaseTool, GuardProtocol, ParameterSpec


class FileSystemTool(BaseTool):
    """Read, write, and list files within a sandboxed base directory.

    Parameters:
        base_dir: Root directory that all file operations are confined to.
            Defaults to the current working directory.
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "filesystem",
            description="Read, write, and list files within a sandboxed directory",
            tags=["filesystem", "io"],
            guards=guards,
            parameters=[
                ParameterSpec(
                    name="action", type_annotation="str", description="One of: read, write, list", required=True
                ),
                ParameterSpec(
                    name="path", type_annotation="str", description="Relative path within base_dir", required=True
                ),
                ParameterSpec(
                    name="content",
                    type_annotation="str | None",
                    description="Content to write (for 'write' action)",
                    required=False,
                    default=None,
                ),
            ],
        )
        self._base_dir = Path(base_dir) if base_dir else Path.cwd()

    def _resolve(self, relative: str) -> Path:
        """Resolve *relative* under base_dir and ensure it does not escape."""
        resolved = (self._base_dir / relative).resolve()
        base_resolved = self._base_dir.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise PermissionError(f"Path '{relative}' escapes the sandbox directory")
        return resolved

    async def _execute(self, **kwargs: Any) -> str | list[str]:
        action: str = kwargs["action"]
        path: str = kwargs["path"]

        if action == "read":
            target = self._resolve(path)
            return target.read_text(encoding="utf-8")

        if action == "write":
            target = self._resolve(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = kwargs.get("content", "")
            target.write_text(content, encoding="utf-8")
            return f"Written {len(content)} bytes to {path}"

        if action == "list":
            target = self._resolve(path)
            if not target.is_dir():
                return [str(target.name)]
            return sorted(e.name for e in target.iterdir())

        raise ValueError(f"Unknown action '{action}'; expected read, write, or list")
