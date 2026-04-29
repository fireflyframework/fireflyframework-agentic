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

"""Tests for pipeline usage aggregation."""

from __future__ import annotations

from fireflyframework_agentic.observability.usage import UsageRecord, default_usage_tracker
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, DAGNode
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.result import NodeResult, PipelineResult


class _EchoStep:
    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    async def execute(self, context, inputs):
        return f"{self._prefix}{inputs.get('input', '')}"


class TestPipelineResultUsage:
    def test_pipeline_result_has_usage_field(self):
        result = PipelineResult(pipeline_name="test")
        assert result.usage is None

    def test_node_result_has_usage_field(self):
        result = NodeResult(node_id="n1")
        assert result.usage is None

    async def test_pipeline_run_includes_usage(self):
        """When usage records exist for the correlation_id, PipelineResult.usage is populated."""
        dag = DAG("usage-test")
        dag.add_node(DAGNode(node_id="a", step=_EchoStep("A:")))
        engine = PipelineEngine(dag)

        ctx = PipelineContext(inputs="hello", correlation_id="test-corr-1")

        # Pre-populate the tracker with a record matching the correlation_id
        default_usage_tracker.reset()

        default_usage_tracker.record(
            UsageRecord(
                correlation_id="test-corr-1",
                agent="pipeline-agent",
                total_tokens=500,
                cost_usd=0.01,
            )
        )

        result = await engine.run(context=ctx)
        assert result.success is True
        assert result.usage is not None
        assert result.usage.total_tokens == 500
        assert result.usage.total_cost_usd == 0.01

        # Clean up
        default_usage_tracker.reset()

    async def test_pipeline_run_no_usage_records(self):
        """PipelineResult.usage is None when no records exist for the correlation_id."""
        dag = DAG("no-usage")
        dag.add_node(DAGNode(node_id="a", step=_EchoStep("A:")))
        engine = PipelineEngine(dag)

        default_usage_tracker.reset()

        ctx = PipelineContext(inputs="hello", correlation_id="unused-corr")
        result = await engine.run(context=ctx)
        assert result.success is True
        assert result.usage is None

        default_usage_tracker.reset()


class TestPipelineEngineAggregateUsage:
    def test_aggregate_usage_returns_none_when_empty(self):
        default_usage_tracker.reset()
        result = PipelineEngine._aggregate_usage("nonexistent")
        assert result is None

    def test_aggregate_usage_returns_summary(self):
        default_usage_tracker.reset()
        default_usage_tracker.record(
            UsageRecord(
                correlation_id="agg-test",
                total_tokens=100,
                cost_usd=0.005,
            )
        )
        default_usage_tracker.record(
            UsageRecord(
                correlation_id="agg-test",
                total_tokens=200,
                cost_usd=0.01,
            )
        )
        result = PipelineEngine._aggregate_usage("agg-test")
        assert result is not None
        assert result.record_count == 2
        assert result.total_tokens == 300
        assert abs(result.total_cost_usd - 0.015) < 1e-9

        default_usage_tracker.reset()
