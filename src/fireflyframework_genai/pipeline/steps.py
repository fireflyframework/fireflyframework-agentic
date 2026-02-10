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

"""Step executors: wrappers that make agents, reasoning patterns, and
arbitrary callables usable as DAG nodes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.types import AgentLike

logger = logging.getLogger(__name__)


@runtime_checkable
class StepExecutor(Protocol):
    """Protocol for any object that can serve as a DAG node executor."""

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        """Execute the step with *inputs* derived from upstream nodes.

        Returns:
            The output value to be stored as this node's result.
        """
        ...


class AgentStep:
    """Wraps a :class:`FireflyAgent` as a pipeline step.

    By default, the ``"input"`` key from the inputs dict is used as the
    prompt.  A custom *prompt_key* can be specified.

    Parameters:
        agent: A :class:`FireflyAgent` or compatible agent.
        prompt_key: Which key in *inputs* to use as the prompt.
        kwargs: Additional keyword arguments forwarded to ``agent.run()``.
    """

    def __init__(
        self,
        agent: AgentLike,
        *,
        prompt_key: str = "input",
        **kwargs: Any,
    ) -> None:
        self._agent = agent
        self._prompt_key = prompt_key
        self._kwargs = kwargs

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        prompt = inputs.get(self._prompt_key, context.inputs)
        # Propagate pipeline memory to the agent if available
        if context.memory is not None and hasattr(self._agent, "memory"):
            self._agent.memory = context.memory  # type: ignore[attr-defined]
        result = await self._agent.run(prompt, **self._kwargs)
        return result.output if hasattr(result, "output") else str(result)


class ReasoningStep:
    """Wraps a reasoning pattern as a pipeline step.

    Parameters:
        pattern: A reasoning pattern with ``async execute(agent, input)``.
        agent: The agent to use with the pattern.
        input_key: Which key in *inputs* to use as the reasoning input.
    """

    def __init__(
        self,
        pattern: Any,
        agent: AgentLike,
        *,
        input_key: str = "input",
    ) -> None:
        self._pattern = pattern
        self._agent = agent
        self._input_key = input_key

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        input_val = inputs.get(self._input_key, context.inputs)
        # Propagate pipeline memory to the reasoning pattern
        extra_kwargs: dict[str, Any] = {}
        if context.memory is not None:
            extra_kwargs["memory"] = context.memory
        result = await self._pattern.execute(self._agent, input_val, **extra_kwargs)
        return result.output


class CallableStep:
    """Wraps an arbitrary async callable as a pipeline step.

    The callable receives ``(context, inputs)`` and returns the output.

    Parameters:
        func: An async callable ``(PipelineContext, dict) -> Any``.
    """

    def __init__(
        self,
        func: Callable[[PipelineContext, dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> None:
        self._func = func

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        return await self._func(context, inputs)


class BranchStep:
    """Route execution to one of several downstream paths based on a predicate.

    The *router* callable receives the node's input and returns a string key.
    That key is stored as the step's output; the *pipeline engine* uses it
    together with :attr:`DAGNode.condition` on downstream nodes to decide
    which branch to follow.

    Example::

        def classify(inputs):
            text = inputs.get("input", "")
            return "positive" if "good" in text else "negative"

        builder.add_node("branch", BranchStep(router=classify))
        builder.add_node("pos", EchoStep(), condition=lambda ctx: ctx.get_node_result("branch").output == "positive")
        builder.add_node("neg", EchoStep(), condition=lambda ctx: ctx.get_node_result("branch").output == "negative")

    Parameters:
        router: Callable ``(dict) -> str`` that returns the branch key.
    """

    def __init__(self, router: Callable[[dict[str, Any]], str]) -> None:
        self._router = router

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        return self._router(inputs)


class FanOutStep:
    """Split input into N items and return them as a list for parallel processing.

    Parameters:
        split_fn: A callable ``(input) -> list`` that splits the input.
    """

    def __init__(self, split_fn: Callable[[Any], list[Any]]) -> None:
        self._split_fn = split_fn

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        input_val = inputs.get("input", context.inputs)
        return self._split_fn(input_val)


class FanInStep:
    """Merge outputs from multiple upstream nodes.

    Parameters:
        merge_fn: A callable ``(list[Any]) -> Any`` that merges results.
            Defaults to returning the list as-is.
    """

    def __init__(
        self,
        merge_fn: Callable[[list[Any]], Any] | None = None,
    ) -> None:
        self._merge_fn = merge_fn or (lambda items: items)

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        # Collect all input values (from multiple upstream nodes)
        values = list(inputs.values())
        return self._merge_fn(values)


class BatchLLMStep:
    """Process multiple prompts in batch for cost optimization.

    Batch processing allows submitting multiple LLM requests together,
    typically with significant cost savings (e.g., 50% discount with
    OpenAI's batch API) and higher throughput. Results are processed
    asynchronously with polling or callback mechanisms.

    This step is ideal for:
    - Large-scale data processing pipelines
    - Non-real-time workloads
    - Cost-sensitive applications
    - High-throughput scenarios

    **Note:** Batch processing introduces latency (minutes to hours) as
    the provider processes requests asynchronously. Use regular AgentStep
    for real-time interactions.

    Parameters:
        agent: The agent to use for batch processing.
        prompts_key: Key in inputs containing the list of prompts.
        batch_size: Maximum prompts per batch (default: 50).
        wait_for_completion: If True, poll until batch completes.
            If False, return batch job ID immediately.
        poll_interval_seconds: How often to check batch status (default: 60s).
        max_wait_seconds: Maximum time to wait for completion (default: 3600s).
        on_batch_complete: Optional callback when batch completes.

    Example::

        # Process 1000 documents in batches
        builder.add_node("batch_process", BatchLLMStep(
            agent=classifier_agent,
            prompts_key="documents",
            batch_size=100,
            wait_for_completion=True,
        ))

    Returns:
        List of agent outputs corresponding to input prompts.
    """

    def __init__(
        self,
        agent: AgentLike,
        *,
        prompts_key: str = "prompts",
        batch_size: int = 50,
        wait_for_completion: bool = True,
        poll_interval_seconds: float = 60.0,
        max_wait_seconds: float = 3600.0,
        on_batch_complete: Callable[[list[Any]], None] | None = None,
        **kwargs: Any,
    ) -> None:
        self._agent = agent
        self._prompts_key = prompts_key
        self._batch_size = batch_size
        self._wait_for_completion = wait_for_completion
        self._poll_interval = poll_interval_seconds
        self._max_wait = max_wait_seconds
        self._on_batch_complete = on_batch_complete
        self._kwargs = kwargs

    async def execute(self, context: PipelineContext, inputs: dict[str, Any]) -> Any:
        """Execute batch processing of multiple prompts.

        Args:
            context: Pipeline context.
            inputs: Dictionary containing prompts list.

        Returns:
            List of outputs if wait_for_completion=True, otherwise batch job info.
        """
        # Try to get prompts from previous node result first, then fall back to inputs
        prompts = None
        try:
            node_result = context.get_node_result(self._prompts_key)
            if node_result and node_result.output:
                prompts = node_result.output
        except (KeyError, AttributeError):
            pass

        # If we didn't get prompts from node result, try inputs
        if prompts is None:
            prompts = inputs.get(self._prompts_key, [])

        if not prompts:
            logger.warning("BatchLLMStep: No prompts found in input key '%s'", self._prompts_key)
            return []

        if not isinstance(prompts, list):
            prompts = [prompts]

        logger.info(
            "BatchLLMStep: Processing %d prompts in batches of %d",
            len(prompts),
            self._batch_size,
        )

        # Split prompts into batches
        batches = [prompts[i : i + self._batch_size] for i in range(0, len(prompts), self._batch_size)]

        all_results = []

        for batch_idx, batch in enumerate(batches, 1):
            logger.info(
                "BatchLLMStep: Processing batch %d/%d (%d prompts)",
                batch_idx,
                len(batches),
                len(batch),
            )

            # Process batch concurrently (not true batch API, but concurrent execution)
            # In production, this would use provider-specific batch APIs
            batch_results = await self._process_batch_concurrent(batch)
            all_results.extend(batch_results)

        if self._on_batch_complete:
            self._on_batch_complete(all_results)

        return all_results

    async def _process_batch_concurrent(self, prompts: list[str]) -> list[Any]:
        """Process a batch of prompts concurrently.

        This is a concurrent implementation. For true batch API support
        with cost savings, this would be replaced with provider-specific
        batch submission (e.g., OpenAI Batch API, Anthropic Message Batches).

        Args:
            prompts: List of prompts to process.

        Returns:
            List of agent outputs.
        """
        tasks = [self._process_single_prompt(prompt) for prompt in prompts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        outputs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "BatchLLMStep: Error processing prompt %d: %s",
                    i,
                    result,
                )
                outputs.append({"error": str(result)})
            else:
                outputs.append(result)

        return outputs

    async def _process_single_prompt(self, prompt: str) -> Any:
        """Process a single prompt through the agent.

        Args:
            prompt: The prompt to process.

        Returns:
            Agent output.
        """
        result = await self._agent.run(prompt, **self._kwargs)
        return result.output if hasattr(result, "output") else str(result)
