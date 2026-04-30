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

"""Experiment execution engine.

:class:`ExperimentRunner` runs all variants of an experiment against the
configured dataset and collects structured results.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fireflyframework_agentic.experiments.experiment import Experiment
from fireflyframework_agentic.experiments.tracker import ExperimentTracker, VariantResult

logger = logging.getLogger(__name__)


class ExperimentRunner:
    """Executes experiment variants and collects results.

    Parameters:
        tracker: An :class:`ExperimentTracker` to persist results.
    """

    def __init__(self, tracker: ExperimentTracker | None = None) -> None:
        self._tracker = tracker or ExperimentTracker()

    async def run(
        self,
        experiment: Experiment,
        agent_factory: Any,
        *,
        context: Any = None,
    ) -> list[VariantResult]:
        """Run all variants of *experiment*.

        Parameters:
            experiment: The experiment to execute.
            agent_factory: A callable ``(variant) -> agent`` that creates an
                agent configured for the given variant.
            context: Optional :class:`AgentContext`.  When provided,
                ``experiment_id`` is set automatically and the context is
                forwarded to each agent run for correlation.

        Returns:
            A list of :class:`VariantResult` objects.
        """
        from fireflyframework_agentic.agents.context import AgentContext

        if context is None:
            context = AgentContext()
        context.experiment_id = experiment.name

        results: list[VariantResult] = []

        for variant in experiment.variants:
            logger.info("Running variant '%s' for experiment '%s'", variant.name, experiment.name)
            agent = agent_factory(variant)
            outputs: list[str] = []
            total_latency = 0.0

            for input_text in experiment.dataset:
                start = time.perf_counter()
                try:
                    result = await agent.run(input_text, context=context)
                except TypeError:
                    # Agent does not accept a context parameter
                    result = await agent.run(input_text)
                elapsed = (time.perf_counter() - start) * 1000
                output = str(result.output if hasattr(result, "output") else result)
                outputs.append(output)
                total_latency += elapsed

            avg_latency = total_latency / len(experiment.dataset) if experiment.dataset else 0
            variant_result = VariantResult(
                experiment_name=experiment.name,
                variant_name=variant.name,
                outputs=outputs,
                avg_latency_ms=avg_latency,
                total_runs=len(experiment.dataset),
            )
            results.append(variant_result)
            self._tracker.record(variant_result)

        return results
