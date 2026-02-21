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

"""Global reasoning pattern registry."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fireflyframework_genai.exceptions import ReasoningPatternNotFoundError

logger = logging.getLogger(__name__)


class ReasoningPatternRegistry:
    """Central registry for reasoning pattern instances or classes."""

    def __init__(self) -> None:
        self._patterns: dict[str, Any] = {}
        self._lock = threading.Lock()

    def register(self, name: str, pattern: Any) -> None:
        """Register *pattern* under *name*."""
        with self._lock:
            self._patterns[name] = pattern
        logger.debug("Registered reasoning pattern '%s'", name)

    def get(self, name: str) -> Any:
        """Return the pattern registered under *name*.

        Raises:
            ReasoningPatternNotFoundError: If *name* is not registered.
        """
        with self._lock:
            try:
                return self._patterns[name]
            except KeyError:
                raise ReasoningPatternNotFoundError(f"No reasoning pattern registered with name '{name}'") from None

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._patterns

    def list_patterns(self) -> list[str]:
        with self._lock:
            return list(self._patterns.keys())

    def clear(self) -> None:
        with self._lock:
            self._patterns.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._patterns)


# Module-level singleton
reasoning_registry = ReasoningPatternRegistry()


def _auto_register_builtins() -> None:
    """Lazily register the six built-in reasoning patterns."""
    try:
        from fireflyframework_genai.reasoning.chain_of_thought import ChainOfThoughtPattern
        from fireflyframework_genai.reasoning.goal_decomposition import GoalDecompositionPattern
        from fireflyframework_genai.reasoning.plan_and_execute import PlanAndExecutePattern
        from fireflyframework_genai.reasoning.react import ReActPattern
        from fireflyframework_genai.reasoning.reflexion import ReflexionPattern
        from fireflyframework_genai.reasoning.tree_of_thoughts import TreeOfThoughtsPattern

        for name, cls in [
            ("react", ReActPattern),
            ("chain_of_thought", ChainOfThoughtPattern),
            ("plan_and_execute", PlanAndExecutePattern),
            ("reflexion", ReflexionPattern),
            ("tree_of_thoughts", TreeOfThoughtsPattern),
            ("goal_decomposition", GoalDecompositionPattern),
        ]:
            if not reasoning_registry.has(name):
                reasoning_registry.register(name, cls)
    except Exception:  # noqa: BLE001
        logger.debug("Could not auto-register built-in reasoning patterns", exc_info=True)


_auto_register_builtins()
