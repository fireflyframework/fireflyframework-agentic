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

"""The generate -> validate -> execute -> capture loop for secure execution.

:class:`SecureScriptRunner` ties a static safety pre-screen, a sandboxed
:class:`ExecutionEnvironment`, and an optional output-scrubbing pass into one
call. Code that fails the pre-screen never reaches the sandbox; captured output
can be redacted (e.g. via the security layer's ``OutputGuard``) before results
re-enter a model's context.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fireflyframework_agentic.execution.environment import ExecutionEnvironment
from fireflyframework_agentic.execution.safety import SafetyPolicy, analyze_code
from fireflyframework_agentic.execution.types import ExecutionLimits, ExecutionResult

logger = logging.getLogger(__name__)


class SecureScriptRunner:
    """Run guest/generated code through safety -> sandbox -> capture.

    Args:
        environment: The sandbox backend (e.g. :class:`MontyEnvironment`).
        policy: Safety policy for the static pre-screen (defaults applied).
        output_scrubber: Optional ``str -> str`` applied to captured ``stdout``
            before it is returned — wire the security ``OutputGuard`` here to
            redact secrets/PII from results.
    """

    def __init__(
        self,
        environment: ExecutionEnvironment,
        *,
        policy: SafetyPolicy | None = None,
        output_scrubber: Callable[[str], str] | None = None,
    ) -> None:
        self._env = environment
        self._policy = policy or SafetyPolicy()
        self._scrub = output_scrubber

    async def execute(
        self,
        code: str,
        *,
        inputs: dict[str, Any] | None = None,
        external_functions: dict[str, Callable[..., Any]] | None = None,
        limits: ExecutionLimits | None = None,
        skip_safety: bool = False,
    ) -> ExecutionResult:
        """Validate, run, and capture ``code``.

        Returns an :class:`ExecutionResult`. When the safety pre-screen rejects
        the code, the sandbox is never invoked and the result carries
        ``error_type="CodeSafetyError"`` plus the per-line ``violations``.
        """
        if not skip_safety:
            report = analyze_code(code, self._policy)
            if not report.safe:
                logger.info("SecureScriptRunner rejected code: %s", report.messages())
                return ExecutionResult(
                    success=False,
                    error="code rejected by the safety pre-screen",
                    error_type="CodeSafetyError",
                    violations=report.messages(),
                )

        result = await self._env.run_code(
            code, inputs=inputs, external_functions=external_functions, limits=limits
        )

        if self._scrub is not None and result.stdout:
            result.stdout = self._scrub(result.stdout)
        return result
