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

"""Reasoning pattern abstraction: protocol and abstract base class.

The reasoning system follows a three-layer extensibility model:

1. :class:`ReasoningPattern` -- a ``typing.Protocol`` that any object can
   satisfy via duck typing.
2. :class:`AbstractReasoningPattern` -- a Template Method ABC that provides
   trace recording, step counting, max-steps enforcement, structured output
   via :meth:`_structured_run`, memory integration, and error handling.
3. Concrete implementations (ReAct, PlanAndExecute, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models import Model

from fireflyframework_genai.exceptions import ReasoningError, ReasoningStepLimitError
from fireflyframework_genai.prompts.template import PromptTemplate
from fireflyframework_genai.reasoning.trace import (
    ReasoningResult,
    ReasoningStep,
    ReasoningTrace,
)
from fireflyframework_genai.types import AgentLike, UserContent

if TYPE_CHECKING:
    from fireflyframework_genai.memory.manager import MemoryManager
    from fireflyframework_genai.validation.reviewer import OutputReviewer

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class ReasoningPattern(Protocol):
    """Protocol that any reasoning pattern must satisfy.

    Third-party code can implement this via duck typing without importing
    any framework base class.
    """

    async def execute(self, agent: AgentLike, input: str | Sequence[UserContent], **kwargs: Any) -> ReasoningResult:
        """Run the reasoning pattern using *agent* on *input*."""
        ...


class AbstractReasoningPattern(ABC):
    """Template Method base class for reasoning patterns.

    Subclasses override hooks such as :meth:`_reason`, :meth:`_act`,
    :meth:`_observe`, and :meth:`_should_continue`.  The base class
    manages the outer loop, trace recording, step counting, structured
    output, memory integration, and error handling.

    Parameters:
        name: Pattern name (used in traces and registry).
        max_steps: Maximum number of iterations before the pattern stops.
        model: Optional LLM model string or :class:`pydantic_ai.models.Model`
            for structured output calls.  When *None*, the model is resolved
            from the agent at execution time.
        prompts: Optional mapping of prompt-slot names (e.g. ``"thought"``,
            ``"plan"``) to :class:`PromptTemplate` overrides.  Slots that
            are not overridden use the built-in defaults.
        reviewer: Optional :class:`OutputReviewer` that validates and
            retries the final output of the pattern.
        step_timeout: Per-step timeout in seconds for LLM calls.  When
            *None* (default), no timeout is applied.
    """

    def __init__(
        self,
        name: str,
        *,
        max_steps: int = 10,
        model: str | Model | None = None,
        prompts: dict[str, PromptTemplate] | None = None,
        reviewer: OutputReviewer | None = None,
        step_timeout: float | None = None,
    ) -> None:
        self._name = name
        self._max_steps = max_steps
        self._model = model
        self._prompts: dict[str, PromptTemplate] = prompts or {}
        self._reviewer = reviewer
        self._step_timeout = step_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def prompts(self) -> dict[str, PromptTemplate]:
        """Prompt template overrides for this pattern."""
        return self._prompts

    @property
    def reviewer(self) -> OutputReviewer | None:
        """Optional output reviewer for final output validation."""
        return self._reviewer

    def _get_prompt(self, slot: str, default: PromptTemplate) -> PromptTemplate:
        """Return the prompt for *slot*, falling back to *default*."""
        return self._prompts.get(slot, default)

    # -- Structured output ---------------------------------------------------

    @staticmethod
    def _resolve_model(agent: AgentLike) -> str | Model | None:
        """Extract the LLM model from an agent.

        Supports :class:`FireflyAgent` (``agent.agent.model``),
        ``pydantic_ai.Agent`` (``agent.model``), or any duck-typed
        object with a ``model`` attribute.
        """
        # FireflyAgent wraps a pydantic_ai Agent in .agent
        inner = getattr(agent, "agent", None)
        if inner is not None:
            model = getattr(inner, "model", None)
            if model is not None:
                return model
        # Direct pydantic_ai Agent or duck-typed
        model = getattr(agent, "model", None)
        return model

    async def _structured_run(
        self,
        agent: AgentLike,
        prompt: str,
        output_type: type[T],
        *,
        correlation_id: str = "",
    ) -> T:
        """Make an LLM call that returns a validated Pydantic model.

        If a model is available (from constructor or resolved from agent),
        an ephemeral :class:`pydantic_ai.Agent` is created with the proper
        ``output_type`` so the LLM is constrained to produce the schema.

        When no model is available, falls back to calling ``agent.run()``
        and parsing the raw output through :meth:`_fallback_parse`.

        Applies :attr:`_step_timeout` when set.
        """
        resolved_model = self._model or self._resolve_model(agent)
        t0 = time.monotonic()
        logger.debug("_structured_run: requesting %s (timeout=%s)", output_type.__name__, self._step_timeout)

        _result_holder: list[Any] = []  # capture result for usage tracking

        async def _call() -> T:
            if resolved_model is not None:
                ephemeral = PydanticAgent(resolved_model, output_type=output_type)
                result = await ephemeral.run(prompt)
                _result_holder.append(result)
                return result.output
            # Fallback: call agent directly and parse
            result = await agent.run(prompt)
            _result_holder.append(result)
            raw = result.output if hasattr(result, "output") else result
            return self._fallback_parse(raw, output_type)

        try:
            if self._step_timeout is not None:
                out = await asyncio.wait_for(_call(), timeout=self._step_timeout)
            else:
                out = await _call()
        except TimeoutError:
            elapsed = time.monotonic() - t0
            raise ReasoningError(f"LLM call for {output_type.__name__} timed out after {elapsed:.1f}s") from None

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug("_structured_run: got %s in %.1fms", output_type.__name__, elapsed_ms)

        # Record usage from the ephemeral agent result
        if _result_holder:
            self._record_structured_usage(
                _result_holder[0],
                elapsed_ms,
                model=str(resolved_model) if resolved_model else "",
                correlation_id=correlation_id,
            )

        return out

    @staticmethod
    def _fallback_parse(raw: Any, output_type: type[T]) -> T:
        """Parse raw agent output into *output_type* using a cascade.

        1. Already the correct type → return as-is.
        2. ``dict`` → ``model_validate()``.
        3. ``str`` → ``model_validate_json()``.
        4. Type-specific fallbacks for known reasoning models.
        """
        if isinstance(raw, output_type):
            return raw

        if isinstance(raw, dict):
            try:
                return output_type.model_validate(raw)
            except ValidationError:
                pass

        raw_str = str(raw)

        try:
            return output_type.model_validate_json(raw_str)
        except (ValidationError, ValueError):
            pass

        # Type-specific text fallbacks
        from fireflyframework_genai.reasoning.models import (
            BranchEvaluation,
            GoalDecompositionResult,
            GoalPhase,
            PlanStepDef,
            ReasoningPlan,
            ReasoningThought,
            ReflectionVerdict,
        )

        if output_type is ReasoningThought:
            return ReasoningThought(content=raw_str)  # type: ignore[return-value]
        if output_type is ReflectionVerdict:
            return ReflectionVerdict(is_satisfactory=True)  # type: ignore[return-value]
        if output_type is ReasoningPlan:
            lines = [ln.strip() for ln in raw_str.strip().split("\n") if ln.strip()]
            steps = [PlanStepDef(id=f"step_{i + 1}", description=ln) for i, ln in enumerate(lines)]
            return ReasoningPlan(goal="", steps=steps)  # type: ignore[return-value]
        if output_type is BranchEvaluation:
            try:
                score = max(0.0, min(1.0, float(raw_str.strip())))
            except ValueError:
                score = 0.5
            return BranchEvaluation(branch_id=0, score=score)  # type: ignore[return-value]
        if output_type is GoalDecompositionResult:
            lines = [ln.strip() for ln in raw_str.strip().split("\n") if ln.strip()]
            phases = [GoalPhase(name=ln) for ln in lines]
            return GoalDecompositionResult(goal="", phases=phases)  # type: ignore[return-value]

        from fireflyframework_genai.reasoning.models import BranchList

        if output_type is BranchList:
            branches = [b.strip() for b in raw_str.split("---") if b.strip()]
            return BranchList(branches=branches or [raw_str])  # type: ignore[return-value]

        # Last resort: try to construct with content= field
        try:
            return output_type(content=raw_str)  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            raise ReasoningError(f"Cannot parse output into {output_type.__name__}: {raw_str[:200]}") from None

    # -- Memory integration --------------------------------------------------

    @staticmethod
    def _init_memory(memory: Any, pattern_name: str) -> MemoryManager | None:
        """Fork a :class:`MemoryManager` for this pattern's working scope.

        If *memory* is not a ``MemoryManager`` (or is ``None``), returns
        ``None`` and memory integration is disabled.
        """
        from fireflyframework_genai.memory.manager import MemoryManager

        if isinstance(memory, MemoryManager):
            return memory.fork(working_scope_id=f"reasoning:{pattern_name}")
        return None

    @staticmethod
    def _persist_step(
        memory: MemoryManager | None,
        step: ReasoningStep | None,
        step_num: int,
    ) -> None:
        """Write a reasoning step to working memory (if available)."""
        if memory is None or step is None:
            return
        # Store the step summary under a namespaced key.
        step_data = step.model_dump() if hasattr(step, "model_dump") else str(step)
        memory.set_fact(f"reasoning:step:{step_num}", step_data)
        # Also maintain a last-step pointer for easy access.
        memory.set_fact("reasoning:last_step", step_data)

    @staticmethod
    def _enrich_prompt(prompt: str, memory: MemoryManager | None) -> str:
        """Prepend working memory context to a prompt when available."""
        if memory is None:
            return prompt
        context = memory.get_working_context()
        if not context:
            return prompt
        return f"{context}\n\n{prompt}"

    # -- Execute loop --------------------------------------------------------

    async def execute(self, agent: AgentLike, input: str | Sequence[UserContent], **kwargs: Any) -> ReasoningResult:
        """Run the reasoning loop.

        *input* may be a plain string or a sequence of multimodal
        :class:`~fireflyframework_genai.types.UserContent` parts.

        If ``memory`` is passed as a keyword argument (a
        :class:`~fireflyframework_genai.memory.manager.MemoryManager`),
        the pattern forks it into an isolated working-memory scope and
        automatically persists each reasoning step.  Working memory
        context is available to subclass hooks via ``state["memory"]``.

        1. Initialise state and trace.
        2. Loop: ``_reason`` → ``_act`` → ``_observe`` → ``_should_continue``.
        3. Enforce ``max_steps`` and build the result.
        """
        trace = ReasoningTrace(pattern_name=self._name)
        raw_memory = kwargs.pop("memory", None)
        memory = self._init_memory(raw_memory, self._name)
        state: dict[str, Any] = {
            "input": input,
            "agent": agent,
            "memory": memory,
            **kwargs,
        }
        steps = 0
        t_start = time.monotonic()
        logger.info("Pattern '%s' starting (max_steps=%d)", self._name, self._max_steps)

        try:
            completed = False
            while steps < self._max_steps:
                steps += 1
                logger.info("Pattern '%s' iteration %d/%d", self._name, steps, self._max_steps)

                # Reason
                thought = await self._reason(state)
                if thought is not None:
                    trace.add_step(thought)
                    self._persist_step(memory, thought, steps)
                    logger.debug("  reason -> %s", type(thought).__name__)

                # Check if we should stop before acting
                if await self._should_stop(state):
                    logger.info("  early stop triggered")
                    completed = True
                    break

                # Act
                action = await self._act(state)
                if action is not None:
                    trace.add_step(action)
                    self._persist_step(memory, action, steps)
                    logger.debug("  act -> %s", type(action).__name__)

                # Observe
                observation = await self._observe(state, action)
                if observation is not None:
                    trace.add_step(observation)
                    self._persist_step(memory, observation, steps)

                # Continue?
                if not await self._should_continue(state):
                    logger.info("  loop complete after %d iterations", steps)
                    completed = True
                    break

            if not completed and steps >= self._max_steps:
                raise ReasoningStepLimitError(f"Pattern '{self._name}' exceeded {self._max_steps} steps")

            output = await self._extract_output(state)

            # Optional: validate output through reviewer
            if self._reviewer is not None and output is not None:
                output = await self._review_output(state, output)

            # Persist final output to working memory
            if memory is not None:
                memory.set_fact("reasoning:output", str(output)[:1000] if output else "")

            logger.info(
                "Pattern '%s' completed in %.1fs (%d steps)",
                self._name,
                time.monotonic() - t_start,
                steps,
            )
            trace.complete()
            return ReasoningResult(output=output, trace=trace, steps_taken=steps, success=True)

        except ReasoningError:
            trace.complete()
            raise
        except Exception as exc:
            trace.complete()
            raise ReasoningError(f"Pattern '{self._name}' failed at step {steps}: {exc}") from exc

    # -- Hooks (override in subclasses) --------------------------------------

    @abstractmethod
    async def _reason(self, state: dict[str, Any]) -> ReasoningStep | None:
        """Generate reasoning / thought for the current state."""
        ...

    @abstractmethod
    async def _act(self, state: dict[str, Any]) -> ReasoningStep | None:
        """Select and perform an action (e.g. tool call)."""
        ...

    async def _observe(self, state: dict[str, Any], action: ReasoningStep | None) -> ReasoningStep | None:
        """Process the result of the action.  Default: no-op."""
        return None

    async def _should_continue(self, state: dict[str, Any]) -> bool:
        """Return *True* to continue the loop.  Default: stop after one iteration."""
        return False

    async def _should_stop(self, state: dict[str, Any]) -> bool:
        """Early exit before acting.  Default: never stop early."""
        return False

    async def _extract_output(self, state: dict[str, Any]) -> Any:
        """Extract the final output from state.  Default: return state['output']."""
        return state.get("output")

    async def _review_output(self, state: dict[str, Any], output: Any) -> Any:
        """Validate and optionally retry the final output using the reviewer.

        If review fails after all retries, the original output is returned
        with a warning logged (non-fatal by default).
        """
        from fireflyframework_genai.exceptions import OutputReviewError

        reviewer = self._reviewer
        if reviewer is None:
            return output
        try:
            result = await reviewer.review(state["agent"], str(output))
            return result.output
        except OutputReviewError:
            logger.warning(
                "Pattern '%s' output reviewer failed; returning raw output",
                self._name,
            )
            return output

    # -- Usage tracking -------------------------------------------------------

    def _record_structured_usage(
        self,
        result: Any,
        elapsed_ms: float,
        *,
        model: str = "",
        correlation_id: str = "",
    ) -> None:
        """Record usage from an ephemeral agent result."""
        try:
            from fireflyframework_genai.config import get_config

            cfg = get_config()
            if not cfg.cost_tracking_enabled:
                return

            usage = result.usage() if callable(getattr(result, "usage", None)) else None
            if usage is None:
                return

            from fireflyframework_genai.observability.cost import get_cost_calculator
            from fireflyframework_genai.observability.usage import UsageRecord, default_usage_tracker

            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens)
            request_count = getattr(usage, "request_count", 0) or 0

            calculator = get_cost_calculator(cfg.cost_calculator)
            cost = calculator.estimate(model, input_tokens, output_tokens)

            record = UsageRecord(
                agent=f"reasoning:{self._name}",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                request_count=request_count,
                cost_usd=cost,
                latency_ms=elapsed_ms,
                correlation_id=correlation_id,
            )
            default_usage_tracker.record(record)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to record reasoning usage for '%s'", self._name, exc_info=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self._name!r}, max_steps={self._max_steps})"
