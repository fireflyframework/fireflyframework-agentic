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

"""Named-workflow registry, the ``@workflow`` decorator, and the run harness.

A workflow is an async function ``fn(args)`` or ``fn(args, ctx)`` that uses the
DSL primitives. The :func:`workflow` decorator registers it under a name and
returns a :class:`Workflow` whose ``run``/``__call__`` set up the per-run
:class:`WorkflowContext`, validate ``args`` against an optional pydantic schema,
and execute the body.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import uuid
from typing import Any

from fireflyframework_agentic.exceptions import WorkflowBudgetError, WorkflowNotFoundError
from fireflyframework_agentic.workflows.context import (
    WorkflowBudget,
    WorkflowContext,
    _current,
    current_workflow,
)
from fireflyframework_agentic.workflows.journal import Journal
from fireflyframework_agentic.workflows.runner import AgentRunner, DefaultAgentRunner

logger = logging.getLogger(__name__)

EventHandler = Any  # Callable[[str, dict], None]


def _wants_context(fn: Any) -> bool:
    """True when ``fn`` accepts a second positional parameter (the context)."""
    try:
        params = [
            p
            for p in inspect.signature(fn).parameters.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        return False
    return len(params) >= 2


class Workflow:
    """A registered, runnable workflow."""

    def __init__(
        self,
        name: str,
        fn: Any,
        *,
        args_schema: Any | None = None,
        description: str = "",
    ) -> None:
        self.name = name
        self._fn = fn
        self.args_schema = args_schema
        self.description = description or (inspect.getdoc(fn) or "").strip().split("\n", 1)[0]

    async def run(
        self,
        args: Any = None,
        *,
        budget: WorkflowBudget | None = None,
        runner: AgentRunner | None = None,
        journal: Journal | None = None,
        events: EventHandler | None = None,
        run_id: str | None = None,
    ) -> Any:
        """Execute the workflow, returning whatever its body returns.

        Pass the same ``journal`` from a prior run to resume: completed agent
        calls return cached outputs and only new calls run live.
        """
        budget = budget or WorkflowBudget()
        runner = runner or DefaultAgentRunner()
        journal = journal if journal is not None else Journal()
        run_id = run_id or f"{self.name}-{uuid.uuid4().hex[:8]}"

        if self.args_schema is not None and args is not None and not isinstance(args, self.args_schema):
            args = self.args_schema.model_validate(args)

        ctx = WorkflowContext(
            name=self.name,
            run_id=run_id,
            budget=budget,
            runner=runner,
            journal=journal,
            events=events,
            args=args,
        )
        token = _current.set(ctx)
        try:
            ctx.emit("workflow.start", {})
            body = self._fn(args, ctx) if _wants_context(self._fn) else self._fn(args)
            try:
                if budget.max_wall_seconds is not None:
                    result = await asyncio.wait_for(body, budget.max_wall_seconds)
                else:
                    result = await body
            except TimeoutError as exc:
                raise WorkflowBudgetError(
                    f"workflow '{self.name}' exceeded max_wall_seconds={budget.max_wall_seconds}"
                ) from exc
            ctx.emit(
                "workflow.end",
                {"agents": ctx.agents_started, "tokens": ctx.tokens_spent, "cost_usd": ctx.cost_spent_usd},
            )
            return result
        finally:
            _current.reset(token)

    async def __call__(self, args: Any = None, **kwargs: Any) -> Any:
        return await self.run(args, **kwargs)


class WorkflowRegistry:
    """Central registry of named workflows (thread-safe)."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._lock = threading.Lock()

    def register(self, name: str, workflow_obj: Workflow) -> None:
        with self._lock:
            self._workflows[name] = workflow_obj
        logger.debug("Registered workflow '%s'", name)

    def get(self, name: str) -> Workflow:
        with self._lock:
            try:
                return self._workflows[name]
            except KeyError:
                raise WorkflowNotFoundError(f"No workflow registered with name '{name}'") from None

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._workflows

    def list_workflows(self) -> list[str]:
        with self._lock:
            return list(self._workflows.keys())

    def clear(self) -> None:
        with self._lock:
            self._workflows.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._workflows)


# Module-level singleton (mirrors reasoning_registry).
workflow_registry = WorkflowRegistry()


def workflow(
    name: str | None = None,
    *,
    args_schema: Any | None = None,
    description: str = "",
    register: bool = True,
) -> Any:
    """Decorator: turn an async function into a registered :class:`Workflow`.

    Example::

        @workflow(name="deep_research", args_schema=ResearchArgs)
        async def deep_research(args, ctx):
            with phase("search"):
                hits = await parallel([lambda q=q: agent(f"search: {q}") for q in args.queries])
            return await agent("synthesize", deps=hits)
    """

    def decorator(fn: Any) -> Workflow:
        wf_name = name or fn.__name__
        wf = Workflow(wf_name, fn, args_schema=args_schema, description=description)
        if register:
            workflow_registry.register(wf_name, wf)
        return wf

    return decorator


async def run_workflow(
    name: str,
    args: Any = None,
    *,
    budget: WorkflowBudget | None = None,
    runner: AgentRunner | None = None,
    journal: Journal | None = None,
    events: EventHandler | None = None,
    run_id: str | None = None,
) -> Any:
    """Look up a registered workflow by name and run it."""
    wf = workflow_registry.get(name)
    return await wf.run(args, budget=budget, runner=runner, journal=journal, events=events, run_id=run_id)


async def subworkflow(workflow_or_name: str | Workflow, args: Any = None) -> Any:
    """Run another workflow inline as a step of the current one, inheriting its
    budget, concurrency gate, journal, runner and event sink.

    The child's body executes in the **parent's** :class:`WorkflowContext`, so its
    ``agent()`` calls count against the same budget and resume from the same
    journal (one deterministic sequence stream across the whole nested run).
    Returns whatever the child returns. Must be called inside an active workflow;
    to run a workflow in *isolation* (its own budget) call ``other_wf.run(...)``
    directly instead.

    (The child reads its own ``args`` parameter; ``ctx.args`` remains the parent's.)
    """
    ctx = current_workflow()
    wf = workflow_or_name if isinstance(workflow_or_name, Workflow) else workflow_registry.get(workflow_or_name)
    if wf.args_schema is not None and args is not None and not isinstance(args, wf.args_schema):
        args = wf.args_schema.model_validate(args)
    ctx.emit("subworkflow.start", {"name": wf.name})
    result = await (wf._fn(args, ctx) if _wants_context(wf._fn) else wf._fn(args))
    ctx.emit("subworkflow.end", {"name": wf.name})
    return result
