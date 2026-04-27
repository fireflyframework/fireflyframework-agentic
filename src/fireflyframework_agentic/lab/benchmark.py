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

"""Benchmarking harness for agents."""

from __future__ import annotations

import time
from collections.abc import Sequence

from pydantic import BaseModel

from fireflyframework_agentic.types import AgentLike


class BenchmarkResult(BaseModel):
    """Result of a single benchmark run."""

    agent_name: str
    total_runs: int = 0
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


class Benchmark:
    """Run standardised benchmarks across agents.

    Parameters:
        inputs: Test prompts to run through each agent.
    """

    def __init__(self, inputs: Sequence[str]) -> None:
        self._inputs = list(inputs)

    async def run(self, agent: AgentLike, agent_name: str = "") -> BenchmarkResult:
        """Benchmark *agent* against the configured inputs."""
        name = agent_name or getattr(agent, "name", "unknown")
        latencies: list[float] = []

        for prompt in self._inputs:
            start = time.perf_counter()
            await agent.run(prompt)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        latencies.sort()
        n = len(latencies)
        p95_idx = min(int(n * 0.95), n - 1) if n else 0

        return BenchmarkResult(
            agent_name=name,
            total_runs=n,
            avg_latency_ms=sum(latencies) / n if n else 0,
            min_latency_ms=latencies[0] if n else 0,
            max_latency_ms=latencies[-1] if n else 0,
            p95_latency_ms=latencies[p95_idx] if n else 0,
        )
