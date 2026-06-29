"""Async LLM scoring client for judge metrics.

Thin wrapper over the framework :class:`FireflyAgent` that returns validated,
typed structured output. The model spec is ``"<provider>:<model>"`` (e.g.
``"anthropic:claude-sonnet-4-6"``); provider resolution, retries, and JSON
schema enforcement are handled by FireflyAgent / pydantic-ai. API keys are read
by the provider when the agent is first built (on the first :meth:`judge` call),
so constructing a JudgeClient never requires a secret.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from fireflyframework_agentic.agents import FireflyAgent

T = TypeVar("T", bound=BaseModel)

_AGENT_NAME = "evaluation-judge"


def parse_model(spec: str) -> tuple[str, str]:
    """Split "provider:model" -> (provider, model). Bare spec -> ("unknown", spec)."""
    spec = (spec or "").strip()
    if ":" not in spec:
        return "unknown", spec
    provider, model = spec.split(":", 1)
    return provider.strip().lower(), model.strip()


def same_provider(pipeline_model: str, judge_model: str) -> bool:
    """True iff both specs share the same known provider prefix."""
    p, _ = parse_model(pipeline_model)
    j, _ = parse_model(judge_model)
    if p == "unknown" or j == "unknown":
        return False
    return p == j


class JudgeClient:
    """Async multi-provider judge backed by :class:`FireflyAgent`.

    Each ``judge`` call returns a validated instance of the requested pydantic
    ``output_type`` — schema enforcement replaces hand-rolled JSON parsing.
    ``temperature`` is pinned to 0.0 for deterministic verdicts. Agents are built
    lazily and cached per ``(system, output_type, max_tokens)``; transient
    rate-limit / 5xx errors and output-validation failures are retried by
    FireflyAgent / pydantic-ai (``max_retries``).
    """

    def __init__(self, model: str, timeout: int = 120, max_retries: int = 3) -> None:
        self.model_spec = model
        self.provider, self.model = parse_model(model)
        self.timeout = timeout
        self.max_retries = max_retries
        self._agents: dict[tuple[str, type, int], FireflyAgent] = {}

    def _agent(self, system: str, output_type: type[T], max_tokens: int) -> FireflyAgent:
        key = (system, output_type, max_tokens)
        agent = self._agents.get(key)
        if agent is None:
            agent = FireflyAgent(
                name=_AGENT_NAME,
                model=self.model_spec,
                instructions=system,
                output_type=output_type,
                model_settings={"temperature": 0.0, "max_tokens": max_tokens},
                retries=self.max_retries,
                auto_register=False,
            )
            self._agents[key] = agent
        return agent

    async def judge(self, system: str, user: str, output_type: type[T], max_tokens: int = 1024) -> T:
        """Send (system, user) to the model and return a validated ``output_type``.

        Raises on exhausted retries / unknown provider / output that cannot be
        coerced to ``output_type`` — callers must not treat a failure as a verdict.
        """
        agent = self._agent(system, output_type, max_tokens)
        result = await agent.run(user, timeout=self.timeout)
        return result.output
