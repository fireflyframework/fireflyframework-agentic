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

"""Model fallback: automatically retry with backup models on failure.

When a primary model is unavailable or raises an error, the
:class:`FallbackModelWrapper` transparently retries with the next
model in the fallback chain.

Usage::

    from fireflyframework_genai.agents.fallback import FallbackModelWrapper

    wrapper = FallbackModelWrapper(
        models=["openai:gpt-4o", "openai:gpt-4o-mini", "openai:gpt-3.5-turbo"],
    )
    agent = FireflyAgent("my-agent", model=wrapper.primary)
    agent.fallback = wrapper
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from pydantic_ai.models import Model

logger = logging.getLogger(__name__)


class FallbackModelWrapper:
    """Wraps a sequence of models and provides fallback logic.

    On failure, :meth:`next_model` advances to the next model in the
    list.  Once all models are exhausted, it wraps back to the primary.

    Parameters:
        models: Ordered list of model identifiers or :class:`Model`
            objects (primary first).
        max_fallback_attempts: Maximum number of fallback retries.
    """

    def __init__(
        self,
        models: Sequence[str | Model],
        *,
        max_fallback_attempts: int | None = None,
    ) -> None:
        if not models:
            raise ValueError("At least one model must be provided")
        self._models: list[str | Model] = list(models)
        self._max_attempts = max_fallback_attempts or len(self._models)
        self._current_index = 0

    @property
    def primary(self) -> str | Model:
        """The primary (first) model."""
        return self._models[0]

    @property
    def current(self) -> str | Model:
        """The currently selected model."""
        return self._models[self._current_index]

    @property
    def models(self) -> list[str | Model]:
        """All available models."""
        return list(self._models)

    def next_model(self) -> str | Model | None:
        """Advance to the next fallback model.

        Returns the next model identifier or :class:`Model` object,
        or *None* if the maximum number of attempts has been reached.
        """
        next_idx = self._current_index + 1
        if next_idx >= self._max_attempts or next_idx >= len(self._models):
            return None
        self._current_index = next_idx
        model = self._models[self._current_index]
        logger.info("Falling back to model '%s' (index %d)", model, self._current_index)
        return model

    def reset(self) -> None:
        """Reset to the primary model."""
        self._current_index = 0


async def run_with_fallback(
    agent: Any,
    prompt: Any,
    fallback: FallbackModelWrapper,
    *,
    deps: Any = None,
    **kwargs: Any,
) -> Any:
    """Run an agent with automatic model fallback on failure.

    Tries the current model, and on failure advances through the
    fallback chain.  The agent's model is restored to the primary
    after completion (success or full exhaustion).

    Parameters:
        agent: A :class:`FireflyAgent` instance.
        prompt: The prompt to run.
        fallback: The :class:`FallbackModelWrapper` controlling fallback order.
        deps: Dependencies to pass to the agent.
        **kwargs: Additional keyword arguments for ``agent.run()``.

    Returns:
        The agent run result.

    Raises:
        The last exception encountered if all models fail.
    """
    from fireflyframework_genai.model_utils import get_model_identifier

    fallback.reset()
    original_model = agent.agent.model
    original_identifier = agent._model_identifier
    last_error: Exception | None = None

    while True:
        try:
            result = await agent.run(prompt, deps=deps, **kwargs)
            return result
        except Exception as exc:  # noqa: BLE001
            model = fallback.current
            logger.warning("Model '%s' failed: %s", model, exc)
            last_error = exc

            next_model = fallback.next_model()
            if next_model is None:
                break
            # Swap the underlying model on the pydantic_ai agent
            agent.agent.model = next_model
            agent._model_identifier = get_model_identifier(next_model)

    # Restore the original model regardless of outcome
    agent.agent.model = original_model
    agent._model_identifier = original_identifier
    fallback.reset()
    raise last_error  # type: ignore[misc]
