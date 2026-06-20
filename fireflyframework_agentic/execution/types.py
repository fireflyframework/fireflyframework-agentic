# Copyright 2026 Firefly Software Foundation
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

"""Backend-agnostic value types for secure script execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Capability(StrEnum):
    """A host capability an execution environment may grant to guest code.

    Environments are deny-by-default: anything not listed in
    :attr:`ExecutionEnvironment.capabilities` is unavailable to the script.
    """

    COMPUTE = "compute"
    """Pure computation: no I/O of any kind."""

    EXTERNAL_FUNCTIONS = "external_functions"
    """The script may call host functions explicitly registered for the run."""

    FILESYSTEM = "filesystem"
    """The script may read/write an explicitly mounted, scoped filesystem."""

    NETWORK = "network"
    """The script may make network calls (only ever a higher, gated tier)."""


@dataclass(slots=True)
class ExecutionLimits:
    """Resource ceilings for a single script execution.

    ``None`` disables a limit. Backends map these onto their native controls
    (the Monty backend maps them onto its ``ResourceLimits``: ``timeout_seconds``
    → ``max_duration_secs``, ``max_memory_bytes`` → ``max_memory``,
    ``max_allocations`` and ``max_recursion_depth`` pass through).
    """

    timeout_seconds: float | None = None
    max_memory_bytes: int | None = None
    max_allocations: int | None = None
    max_recursion_depth: int | None = None


@dataclass(slots=True)
class ExecutionResult:
    """Outcome of running a script in an :class:`ExecutionEnvironment`.

    Attributes:
        success: ``True`` when the script ran to completion without raising.
        output: The value of the script's final expression (``None`` if absent).
        stdout: Captured standard-output text.
        stderr: Captured standard-error text.
        error: A human-readable error message when ``success`` is ``False``.
        error_type: The originating error class name (e.g. ``"MontyRuntimeError"``
            or ``"CodeSafetyError"``).
    """

    success: bool
    output: Any = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    error_type: str | None = None
    violations: list[str] = field(default_factory=list)
