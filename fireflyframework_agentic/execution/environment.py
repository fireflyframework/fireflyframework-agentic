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

"""The single abstraction over secure execution backends.

Every backend (Monty in-process today; Docker / cloud micro-VM in later tiers)
implements :class:`ExecutionEnvironment`. The tiered, capability-based design
lets a policy select the cheapest sufficiently-isolated backend for a given
script without callers caring which one runs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from fireflyframework_agentic.execution.types import Capability, ExecutionLimits, ExecutionResult


@runtime_checkable
class ExecutionEnvironment(Protocol):
    """A sandboxed environment that runs a Python script and returns its result.

    Implementations are **deny-by-default**: the only host access guest code
    gets is the set of ``external_functions`` explicitly handed to
    :meth:`run_code` for that call.
    """

    @property
    def capabilities(self) -> frozenset[Capability]:
        """The host capabilities this environment can grant."""
        raise NotImplementedError

    async def run_code(
        self,
        code: str,
        *,
        inputs: dict[str, Any] | None = None,
        external_functions: dict[str, Callable[..., Any]] | None = None,
        limits: ExecutionLimits | None = None,
    ) -> ExecutionResult:
        """Execute ``code`` in isolation and capture its result.

        Args:
            code: The Python source to run. The value of its final expression
                becomes :attr:`ExecutionResult.output`.
            inputs: Named values injected as pre-declared variables in the script.
            external_functions: Host callables (sync or async) the script may
                invoke by name — the only sanctioned escape hatch.
            limits: Resource ceilings for this run.

        Returns:
            An :class:`ExecutionResult`; backends report guest exceptions as
            ``success=False`` rather than raising.
        """
        raise NotImplementedError
