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

"""Monty-backed in-process execution environment (tiers 0 and 1).

`Monty <https://pypi.org/project/pydantic-monty/>`_ is a Rust micro-interpreter
with a deny-by-default capability model: guest code gets no filesystem, network,
or environment access, and reaches the host only through ``external_functions``
explicitly registered per run. It supports a Python *subset* (no third-party
packages) — ideal for glue logic over Firefly tools, not for pandas jobs.

This backend requires the ``script-execution`` extra
(``pip install 'fireflyframework-agentic[script-execution]'``).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from fireflyframework_agentic.exceptions import SandboxUnavailableError
from fireflyframework_agentic.execution.types import Capability, ExecutionLimits, ExecutionResult

logger = logging.getLogger(__name__)


def _sync_bridge(coro_fn: Callable[..., Any], loop: asyncio.AbstractEventLoop) -> Callable[..., Any]:
    """Wrap an async external function so guest code can call it without ``await``.

    Monty invokes external functions from a worker thread during ``run_async``; an
    async one would otherwise return an unawaited coroutine. This runs the
    coroutine on the host event loop and blocks the worker thread for its result.
    """

    def _call(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro_fn(*args, **kwargs), loop).result()

    return _call


class MontyEnvironment:
    """A sandboxed :class:`ExecutionEnvironment` backed by pydantic-monty.

    Tier 0 (no ``external_functions``) is pure computation. Tier 1 exposes
    allow-listed host callables to the script via ``external_functions`` — the
    basis of Firefly's Code Mode.

    Args:
        type_check: Run Monty's static type checker before execution.
        default_limits: Baseline resource ceilings applied to every run (a
            runaway-loop safety net). Per-call ``limits`` are merged over these
            field-by-field. Defaults to a 30s wall-clock timeout.
    """

    def __init__(self, *, type_check: bool = False, default_limits: ExecutionLimits | None = None) -> None:
        try:
            import pydantic_monty  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise SandboxUnavailableError(
                "MontyEnvironment requires the 'script-execution' extra: "
                "pip install 'fireflyframework-agentic[script-execution]'"
            ) from exc
        self._type_check = type_check
        self._default_limits = default_limits if default_limits is not None else ExecutionLimits(timeout_seconds=30.0)

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.COMPUTE, Capability.EXTERNAL_FUNCTIONS})

    def _effective_limits(self, limits: ExecutionLimits | None) -> ExecutionLimits:
        base = self._default_limits
        if limits is None:
            return base
        # Per-call fields override the defaults; unset fields keep the safety net.
        return ExecutionLimits(
            timeout_seconds=limits.timeout_seconds if limits.timeout_seconds is not None else base.timeout_seconds,
            max_memory_bytes=limits.max_memory_bytes if limits.max_memory_bytes is not None else base.max_memory_bytes,
            max_allocations=limits.max_allocations if limits.max_allocations is not None else base.max_allocations,
            max_recursion_depth=(
                limits.max_recursion_depth if limits.max_recursion_depth is not None else base.max_recursion_depth
            ),
        )

    def _resource_limits(self, limits: ExecutionLimits | None) -> Any:
        from pydantic_monty import ResourceLimits  # type: ignore[import-not-found]

        eff = self._effective_limits(limits)
        kwargs: dict[str, Any] = {}
        if eff.timeout_seconds is not None:
            kwargs["max_duration_secs"] = eff.timeout_seconds
        if eff.max_memory_bytes is not None:
            kwargs["max_memory"] = eff.max_memory_bytes
        if eff.max_allocations is not None:
            kwargs["max_allocations"] = eff.max_allocations
        if eff.max_recursion_depth is not None:
            kwargs["max_recursion_depth"] = eff.max_recursion_depth
        return ResourceLimits(**kwargs) if kwargs else None

    async def run_code(
        self,
        code: str,
        *,
        inputs: dict[str, Any] | None = None,
        external_functions: dict[str, Callable[..., Any]] | None = None,
        limits: ExecutionLimits | None = None,
    ) -> ExecutionResult:
        from pydantic_monty import (  # type: ignore[import-not-found]
            CollectStreams,
            Monty,
            MontyError,
            MontySyntaxError,
            MontyTypingError,
        )

        input_names = sorted(inputs) if inputs else None
        try:
            interp = Monty(code, inputs=input_names, type_check=self._type_check)
        except (MontySyntaxError, MontyTypingError) as exc:
            return ExecutionResult(success=False, error=str(exc), error_type=type(exc).__name__)

        # Async external functions (e.g. Firefly tools via Code Mode) are bridged
        # to sync so guest code can call them naturally, without `await`.
        bridged = external_functions
        if external_functions:
            loop = asyncio.get_running_loop()
            bridged = {
                name: (_sync_bridge(fn, loop) if inspect.iscoroutinefunction(fn) else fn)
                for name, fn in external_functions.items()
            }

        collector = CollectStreams()
        try:
            output = await interp.run_async(
                inputs=inputs or None,
                limits=self._resource_limits(limits),
                external_functions=bridged or None,
                print_callback=collector,
            )
        except MontyError as exc:
            stdout, stderr = _split_streams(collector)
            return ExecutionResult(
                success=False, error=str(exc), error_type=type(exc).__name__, stdout=stdout, stderr=stderr
            )

        stdout, stderr = _split_streams(collector)
        return ExecutionResult(success=True, output=output, stdout=stdout, stderr=stderr)


def _split_streams(collector: Any) -> tuple[str, str]:
    out: list[str] = []
    err: list[str] = []
    for stream, text in collector.output:
        (out if stream == "stdout" else err).append(text)
    return "".join(out), "".join(err)
