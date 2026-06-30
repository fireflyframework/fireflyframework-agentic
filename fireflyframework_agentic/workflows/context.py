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

"""Per-run orchestration state for the dynamic-workflow engine.

A :class:`WorkflowContext` carries the resource budget, the concurrency gate,
the resume journal, the agent runner, and live telemetry for a single workflow
execution. It is bound to a :class:`contextvars.ContextVar` for the duration of
the run so the DSL primitives (``agent``/``parallel``/``pipeline``/``phase``)
can reach it without threading it through every call. Because ``contextvars``
propagate into tasks spawned by ``asyncio.gather``, primitives invoked inside a
``parallel``/``pipeline`` fan-out see the same context automatically.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fireflyframework_agentic.exceptions import WorkflowBudgetError, WorkflowContextError

if TYPE_CHECKING:
    from fireflyframework_agentic.workflows.journal import Journal
    from fireflyframework_agentic.workflows.runner import AgentRunner

logger = logging.getLogger(__name__)

_DEFAULT_MAX_AGENTS_TOTAL = 1000


def _default_concurrency() -> int:
    """Mirror Claude's default: ``min(16, cpu_count - 2)`` (at least 1)."""
    cpu = os.cpu_count() or 4
    return max(1, min(16, cpu - 2))


@dataclass(slots=True)
class WorkflowBudget:
    """Resource ceilings for one workflow run.

    Attributes:
        max_concurrent_agents: Size of the semaphore gating concurrent
            ``agent()`` calls. Defaults to ``min(16, cpu - 2)``.
        max_agents_total: Hard kill-switch on the number of agents a run may
            start (runaway-loop backstop).
        max_tokens: Optional output-token ceiling for the whole run. ``None``
            disables token budgeting.
    """

    max_concurrent_agents: int = field(default_factory=_default_concurrency)
    max_agents_total: int = _DEFAULT_MAX_AGENTS_TOTAL
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_wall_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_concurrent_agents < 1:
            raise ValueError("max_concurrent_agents must be >= 1")
        if self.max_agents_total < 1:
            raise ValueError("max_agents_total must be >= 1")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens must be >= 1 when set")
        if self.max_cost_usd is not None and self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be > 0 when set")
        if self.max_wall_seconds is not None and self.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be > 0 when set")


# The active workflow context for the current async task tree.
_current: contextvars.ContextVar[WorkflowContext | None] = contextvars.ContextVar(
    "firefly_workflow_context", default=None
)


def current_workflow() -> WorkflowContext:
    """Return the active :class:`WorkflowContext`.

    Raises:
        WorkflowContextError: when called outside an active workflow run.
    """
    ctx = _current.get()
    if ctx is None:
        raise WorkflowContextError(
            "workflow primitive called outside an active workflow; invoke it via "
            "run_workflow(...) or a @workflow-decorated function"
        )
    return ctx


class WorkflowContext:
    """Mutable per-run state shared by every workflow primitive.

    Counters are mutated synchronously (no ``await`` between read and write) so
    they are race-free under a single asyncio event loop. ``next_call_seq`` is
    likewise synchronous and is invoked at the very top of ``agent()`` (before
    any ``await``), which makes sequence assignment deterministic in task-launch
    order — the property the resume journal relies on.
    """

    def __init__(
        self,
        *,
        name: str,
        run_id: str,
        budget: WorkflowBudget,
        runner: AgentRunner,
        journal: Journal,
        events: Callable[[str, dict[str, Any]], None] | None = None,
        args: Any = None,
    ) -> None:
        self.name = name
        self.run_id = run_id
        self.budget = budget
        self.runner = runner
        self.journal = journal
        self.args = args
        self._events = events
        self._semaphore = asyncio.Semaphore(budget.max_concurrent_agents)
        self._agents_started = 0
        self._tokens_spent = 0
        self._cost_spent = 0.0
        self._call_seq = 0
        self._phase_stack: list[str] = []

    # -- phases --------------------------------------------------------------

    @property
    def current_phase(self) -> str | None:
        return self._phase_stack[-1] if self._phase_stack else None

    def push_phase(self, title: str) -> None:
        self._phase_stack.append(title)
        self.emit("phase.start", {"phase": title})

    def pop_phase(self) -> None:
        if self._phase_stack:
            title = self._phase_stack.pop()
            self.emit("phase.end", {"phase": title})

    # -- sequencing & budget -------------------------------------------------

    def next_call_seq(self) -> int:
        self._call_seq += 1
        return self._call_seq

    def reserve_agent(self) -> None:
        """Account for one agent about to run; enforce the agent/token ceilings.

        Raises:
            WorkflowBudgetError: when the total-agent or token ceiling is hit.
        """
        if self._agents_started >= self.budget.max_agents_total:
            raise WorkflowBudgetError(
                f"workflow '{self.name}' exceeded max_agents_total={self.budget.max_agents_total}"
            )
        if self.budget.max_tokens is not None and self._tokens_spent >= self.budget.max_tokens:
            raise WorkflowBudgetError(
                f"workflow '{self.name}' exhausted token budget={self.budget.max_tokens} (spent {self._tokens_spent})"
            )
        if self.budget.max_cost_usd is not None and self._cost_spent >= self.budget.max_cost_usd:
            raise WorkflowBudgetError(
                f"workflow '{self.name}' exhausted cost budget=${self.budget.max_cost_usd:.4f} "
                f"(spent ${self._cost_spent:.4f})"
            )
        self._agents_started += 1

    def record_tokens(self, tokens: int) -> None:
        if tokens:
            self._tokens_spent += int(tokens)

    def record_cost_usd(self, cost: float) -> None:
        if cost:
            self._cost_spent += float(cost)

    @property
    def agents_started(self) -> int:
        return self._agents_started

    @property
    def tokens_spent(self) -> int:
        return self._tokens_spent

    @property
    def cost_spent_usd(self) -> float:
        return self._cost_spent

    def remaining_tokens(self) -> int | None:
        if self.budget.max_tokens is None:
            return None
        return max(0, self.budget.max_tokens - self._tokens_spent)

    def remaining_cost_usd(self) -> float | None:
        if self.budget.max_cost_usd is None:
            return None
        return max(0.0, self.budget.max_cost_usd - self._cost_spent)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    # -- telemetry -----------------------------------------------------------

    def emit(self, event: str, data: dict[str, Any]) -> None:
        """Best-effort emit a structured workflow event to the run's handler."""
        if self._events is None:
            return
        try:
            self._events(event, {"workflow": self.name, "run_id": self.run_id, **data})
        except Exception:  # noqa: BLE001 - telemetry must never break a run
            logger.debug("workflow event handler raised for %r", event, exc_info=True)
