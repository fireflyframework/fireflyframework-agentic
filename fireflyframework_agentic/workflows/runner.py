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

"""Pluggable agent runner for the workflow ``agent()`` primitive.

The runner is the single seam between the orchestration DSL and the LLM. Tests
inject a deterministic fake; production uses :class:`DefaultAgentRunner`, which
runs each call as an ephemeral ``pydantic_ai.Agent`` (mirroring the structured
run path in :mod:`fireflyframework_agentic.reasoning.base`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic_ai import Agent as PydanticAgent

from fireflyframework_agentic.observability.usage import resolve_run_usage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentCall:
    """The outcome of a single workflow ``agent()`` invocation.

    Attributes:
        output: The agent's output (a ``str`` or the validated ``output_type``).
        tokens: Output/total tokens consumed (fed into the run's token budget).
        raw: The underlying result object, when one exists (else ``None``).
    """

    output: Any
    tokens: int = 0
    raw: Any = None


@runtime_checkable
class AgentRunner(Protocol):
    """Strategy that executes one workflow agent call."""

    async def run(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
    ) -> AgentCall:
        """Execute one workflow agent call and return its result."""
        raise NotImplementedError


class DefaultAgentRunner:
    """Runs each call as a fresh ``pydantic_ai.Agent``.

    Each call gets an isolated agent with no shared message history (mirroring
    the context isolation of Claude's workflow sub-agents); context is passed
    only via the prompt/deps. Requires a resolvable model — passed per call to
    ``agent(...)`` or as this runner's ``default_model``.
    """

    def __init__(self, *, default_model: Any | None = None) -> None:
        self._default_model = default_model

    async def run(
        self,
        prompt: Any,
        *,
        model: Any | None = None,
        output_type: Any | None = None,
        instructions: str | None = None,
        deps: Any = None,
        tools: Any | None = None,
        toolsets: Any | None = None,
    ) -> AgentCall:
        resolved = model or self._default_model
        if resolved is None:
            raise ValueError(
                "DefaultAgentRunner requires a model; pass model= to agent() or default_model= to the runner"
            )
        kwargs: dict[str, Any] = {}
        if output_type is not None:
            kwargs["output_type"] = output_type
        if instructions is not None:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = list(tools)
        if toolsets:
            kwargs["toolsets"] = list(toolsets)
        if deps is not None:
            # pydantic-ai validates deps against deps_type; infer it from the value.
            kwargs["deps_type"] = type(deps)
        ephemeral = PydanticAgent(resolved, **kwargs)
        result = await ephemeral.run(prompt, deps=deps)
        usage = resolve_run_usage(result)
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage is not None else 0
        return AgentCall(output=result.output, tokens=tokens, raw=result)
