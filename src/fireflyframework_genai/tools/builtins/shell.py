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

"""Built-in sandboxed shell command execution tool.

Commands are executed within a configurable working directory and are
subject to an allow-list to prevent dangerous operations.
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fireflyframework_genai.tools.base import BaseTool, GuardProtocol, ParameterSpec


class ShellTool(BaseTool):
    """Execute shell commands in a sandboxed environment.

    Only commands whose first token appears in *allowed_commands* are
    permitted.  When *allowed_commands* is empty, all commands are
    rejected (safe default).

    Parameters:
        allowed_commands: Whitelist of executable names (e.g. ``["ls", "cat", "grep"]``).
        working_dir: Directory in which commands are executed.
        timeout: Maximum execution time in seconds.
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        allowed_commands: Sequence[str] = (),
        working_dir: str | Path | None = None,
        timeout: float = 30.0,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "shell",
            description="Execute sandboxed shell commands",
            tags=["shell", "system"],
            guards=guards,
            parameters=[
                ParameterSpec(
                    name="command", type_annotation="str", description="Shell command to execute", required=True
                ),
            ],
        )
        self._allowed = set(allowed_commands)
        self._working_dir = str(Path(working_dir).resolve()) if working_dir else None
        self._timeout = timeout

    async def _execute(self, **kwargs: Any) -> dict[str, Any]:
        command: str = kwargs["command"]
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Empty command")

        executable = parts[0]
        if executable not in self._allowed:
            raise PermissionError(f"Command '{executable}' is not in the allowed list: {sorted(self._allowed)}")

        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except TimeoutError as _err:
            proc.kill()
            raise TimeoutError(f"Command timed out after {self._timeout}s") from _err

        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
