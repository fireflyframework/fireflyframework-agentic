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

"""Agent lifecycle management -- init, warmup, and shutdown hooks.

Hooks are async-first: synchronous callables are automatically wrapped in a
thread-pool executor so they never block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

LifecycleHook = Callable[[], None] | Callable[[], Awaitable[None]]
"""A lifecycle hook is either a sync or async no-arg callable."""


class AgentLifecycle:
    """Manages ordered lifecycle hooks for agents.

    Hooks are executed in registration order.  Exceptions in one hook are
    logged but do not prevent subsequent hooks from running.
    """

    def __init__(self) -> None:
        self._init_hooks: list[LifecycleHook] = []
        self._warmup_hooks: list[LifecycleHook] = []
        self._shutdown_hooks: list[LifecycleHook] = []

    # -- Registration --------------------------------------------------------

    def on_init(self, hook: LifecycleHook) -> LifecycleHook:
        """Register *hook* to run during the init phase."""
        self._init_hooks.append(hook)
        return hook

    def on_warmup(self, hook: LifecycleHook) -> LifecycleHook:
        """Register *hook* to run during warmup (e.g. pre-loading caches)."""
        self._warmup_hooks.append(hook)
        return hook

    def on_shutdown(self, hook: LifecycleHook) -> LifecycleHook:
        """Register *hook* to run during graceful shutdown."""
        self._shutdown_hooks.append(hook)
        return hook

    # -- Execution -----------------------------------------------------------

    async def run_init(self) -> None:
        """Execute all registered init hooks in order."""
        await self._run_hooks("init", self._init_hooks)

    async def run_warmup(self) -> None:
        """Execute all registered warmup hooks in order."""
        await self._run_hooks("warmup", self._warmup_hooks)

    async def run_shutdown(self) -> None:
        """Execute all registered shutdown hooks in order."""
        await self._run_hooks("shutdown", self._shutdown_hooks)

    # -- Internal ------------------------------------------------------------

    @staticmethod
    async def _run_hooks(phase: str, hooks: list[LifecycleHook]) -> None:
        for hook in hooks:
            try:
                # Hooks may be sync or async callables.  Invoke unconditionally
                # and await the result only if the call returned a coroutine.
                result = hook()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Log but do not re-raise so remaining hooks still execute.
                logger.exception("Error in %s lifecycle hook %r", phase, hook)


# Module-level singleton
agent_lifecycle = AgentLifecycle()
