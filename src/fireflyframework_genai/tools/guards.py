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

"""Pre-execution guards for tool invocations.

Guards intercept a tool call before it runs and decide whether execution
should proceed.  They compose via :class:`CompositeGuard` (AND semantics)
and integrate with the :class:`~fireflyframework_genai.tools.base.BaseTool`
guard chain.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fireflyframework_genai.tools.base import GuardProtocol, GuardResult

# Type alias for the human-in-the-loop approval callback
ApprovalCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]


class ValidationGuard:
    """Validates that all required parameters declared in a tool's spec are present.

    Parameters:
        required_keys: Names of keyword arguments that must be supplied.
    """

    def __init__(self, required_keys: Sequence[str]) -> None:
        self._required = list(required_keys)

    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        missing = [k for k in self._required if k not in kwargs]
        if missing:
            return GuardResult(
                passed=False,
                reason=f"Missing required parameters: {', '.join(missing)}",
            )
        return GuardResult(passed=True)


class RateLimitGuard:
    """Token-bucket rate limiter that caps tool invocations over a time window.

    Parameters:
        max_calls: Maximum number of calls allowed per period.
        period_seconds: Length of the rate-limit window in seconds.
    """

    def __init__(self, max_calls: int, period_seconds: float = 60.0) -> None:
        self._max_calls = max_calls
        self._period = period_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        now = time.monotonic()
        with self._lock:
            # Sliding-window rate limiter: discard timestamps that have aged out
            # of the current window, then check if capacity remains.
            self._timestamps = [t for t in self._timestamps if now - t < self._period]
            if len(self._timestamps) >= self._max_calls:
                return GuardResult(
                    passed=False,
                    reason=f"Rate limit exceeded: {self._max_calls} calls per {self._period}s",
                )
            # Record this invocation timestamp to count against the window.
            self._timestamps.append(now)
        return GuardResult(passed=True)


class ApprovalGuard:
    """Human-in-the-loop guard that delegates the decision to an async callback.

    The callback receives the tool name and kwargs and must return ``True``
    to approve execution.

    Parameters:
        callback: An async callable ``(tool_name, kwargs) -> bool``.
    """

    def __init__(self, callback: ApprovalCallback) -> None:
        self._callback = callback

    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        approved = await self._callback(tool_name, kwargs)
        if not approved:
            return GuardResult(passed=False, reason="Execution not approved")
        return GuardResult(passed=True)


class SandboxGuard:
    """Restricts tool arguments by matching against allow / deny regex patterns.

    Values of *all* kwargs are converted to strings and tested.  If any
    value matches a *denied_pattern* (and does not match an
    *allowed_pattern*) the guard rejects execution.

    Parameters:
        allowed_patterns: Regex patterns that explicitly permit a value.
        denied_patterns: Regex patterns that block a value.
    """

    def __init__(
        self,
        *,
        allowed_patterns: Sequence[str] = (),
        denied_patterns: Sequence[str] = (),
    ) -> None:
        self._allowed = [self._safe_compile(p) for p in allowed_patterns]
        self._denied = [self._safe_compile(p) for p in denied_patterns]

    @staticmethod
    def _safe_compile(pattern: str) -> re.Pattern[str]:
        """Compile a regex pattern, raising ValueError on invalid patterns."""
        try:
            return re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern {pattern!r}: {exc}") from exc

    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        # Check every kwarg value against deny patterns.  An allowed pattern
        # can override a deny match (allowlist takes precedence).
        for key, value in kwargs.items():
            val_str = str(value)
            for pattern in self._denied:
                if pattern.search(val_str) and not any(a.search(val_str) for a in self._allowed):
                    return GuardResult(
                        passed=False,
                        reason=f"Parameter '{key}' matched denied pattern '{pattern.pattern}'",
                    )
        return GuardResult(passed=True)


class CompositeGuard:
    """AND-composition of multiple guards.

    All guards must pass for the composite to pass.  Guards are evaluated
    in order; the first failure short-circuits.

    Parameters:
        guards: The guards to compose.
    """

    def __init__(self, guards: Sequence[GuardProtocol]) -> None:
        self._guards = list(guards)

    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        for guard in self._guards:
            result = await guard.check(tool_name, kwargs)
            if not result.passed:
                return result
        return GuardResult(passed=True)
