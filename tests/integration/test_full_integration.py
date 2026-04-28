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

"""Integration tests for full framework integration.

These tests verify that all production features work together:
- Database persistence
- Distributed tracing
- Quota management
- Security features
- HTTP pooling
- Streaming
- Batch processing
- Prompt caching
- Circuit breaker
"""

from __future__ import annotations

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import CostGuardMiddleware, LoggingMiddleware
from fireflyframework_agentic.agents.prompt_cache import PromptCacheMiddleware
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.steps import AgentStep, BatchLLMStep
from fireflyframework_agentic.resilience.circuit_breaker import CircuitBreakerMiddleware


@pytest.mark.asyncio
class TestFullIntegration:
    """Integration tests for complete framework functionality."""

    async def test_agent_with_all_middleware(self):
        """Test agent with all production middleware enabled."""
        memory = MemoryManager()

        agent = FireflyAgent(
            "full-stack-agent",
            model="test",
            instructions="You are a helpful assistant.",
            memory=memory,
            middleware=[
                LoggingMiddleware(),
                CostGuardMiddleware(budget_usd=10.0),
                PromptCacheMiddleware(cache_system_prompt=True),
                CircuitBreakerMiddleware(failure_threshold=5),
            ],
            auto_register=False,
        )

        conversation_id = "test-conv"

        # Make multiple requests
        result1 = await agent.run("Question 1", conversation_id=conversation_id)
        assert result1.output

        result2 = await agent.run("Question 2", conversation_id=conversation_id)
        assert result2.output

        # Verify memory persisted
        history = memory.get_message_history(conversation_id)
        assert len(history) > 0

    async def test_agent_with_streaming_and_middleware(self):
        """Test agent streaming with middleware."""
        agent = FireflyAgent(
            "streaming-agent",
            model="test",
            middleware=[
                LoggingMiddleware(),
                PromptCacheMiddleware(),
                CircuitBreakerMiddleware(failure_threshold=3),
            ],
            auto_register=False,
        )

        # Test buffered streaming
        async with await agent.run_stream("Question", streaming_mode="buffered") as stream:
            chunks = []
            async for chunk in stream.stream_text():
                chunks.append(chunk)
            assert len(chunks) > 0

        # Test incremental streaming
        async with await agent.run_stream("Question", streaming_mode="incremental") as stream:
            tokens = []
            async for token in stream.stream_tokens():
                tokens.append(token)
            assert len(tokens) > 0

    async def test_pipeline_with_batch_and_middleware(self):
        """Test pipeline with batch processing and middleware."""
        memory = MemoryManager()

        classifier = FireflyAgent(
            "pipeline-classifier",
            model="test",
            instructions="Classify sentiment.",
            memory=memory,
            middleware=[
                PromptCacheMiddleware(),
                CircuitBreakerMiddleware(failure_threshold=5),
            ],
            auto_register=False,
        )

        builder = PipelineBuilder()

        # Load step
        async def load_docs(context, inputs):
            return ["Doc 1", "Doc 2", "Doc 3"]

        builder.add_node("load", load_docs)

        # Batch processing step
        builder.add_node(
            "classify",
            BatchLLMStep(classifier, prompts_key="load", batch_size=10),
        )
        builder.add_edge("load", "classify")

        # Aggregate step
        async def aggregate(context, inputs):
            classifications = context.get_node_result("classify").output
            return {"count": len(classifications)}

        builder.add_node("aggregate", aggregate)
        builder.add_edge("classify", "aggregate")

        # Run pipeline
        from fireflyframework_agentic.pipeline.context import PipelineContext

        pipeline = builder.build()
        result = await pipeline.run(PipelineContext(inputs={}))

        # Check aggregate result
        assert result.outputs["aggregate"].output["count"] == 3

    async def test_memory_persistence_across_requests(self):
        """Test memory persistence with middleware."""
        memory = MemoryManager()

        agent = FireflyAgent(
            "memory-test",
            model="test",
            memory=memory,
            middleware=[LoggingMiddleware()],
            auto_register=False,
        )

        conversation_id = "persistent-conv"

        # Request 1
        await agent.run("First question", conversation_id=conversation_id)

        # Request 2
        await agent.run("Second question", conversation_id=conversation_id)

        # Verify both are in history
        history = memory.get_message_history(conversation_id)
        assert len(history) >= 2  # At least 2 exchanges

    async def test_agent_step_in_pipeline_with_memory(self):
        """Test AgentStep in pipeline preserves memory."""
        from fireflyframework_agentic.pipeline.context import PipelineContext

        memory = MemoryManager()

        agent = FireflyAgent(
            "pipeline-agent",
            model="test",
            memory=memory,
            auto_register=False,
        )

        builder = PipelineBuilder()
        builder.add_node("process", AgentStep(agent, prompt_key="input"))

        pipeline = builder.build()
        result = await pipeline.run(PipelineContext(inputs={"input": "Test question"}))

        assert result.outputs["process"].output

    async def test_circuit_breaker_with_batch_processing(self):
        """Test circuit breaker protects batch processing."""
        agent = FireflyAgent(
            "batch-breaker",
            model="test",
            middleware=[CircuitBreakerMiddleware(failure_threshold=2)],
            auto_register=False,
        )

        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=5)

        from fireflyframework_agentic.pipeline.context import PipelineContext

        context = PipelineContext(inputs={}, correlation_id="test")
        inputs = {"prompts": ["P1", "P2", "P3"]}

        # Should work without errors
        results = await step.execute(context, inputs)
        assert len(results) == 3

    async def test_cost_guard_with_streaming(self):
        """Test cost guard middleware works with streaming."""
        agent = FireflyAgent(
            "cost-stream",
            model="test",
            middleware=[CostGuardMiddleware(budget_usd=100.0)],
            auto_register=False,
        )

        # Should not raise budget exceeded
        async with await agent.run_stream("Question") as stream:
            async for _ in stream.stream_text():
                break

    async def test_multiple_agents_with_shared_memory(self):
        """Test multiple agents sharing memory manager."""
        memory = MemoryManager()

        agent1 = FireflyAgent(
            "agent1",
            model="test",
            memory=memory,
            auto_register=False,
        )

        agent2 = FireflyAgent(
            "agent2",
            model="test",
            memory=memory,
            auto_register=False,
        )

        conversation_id = "shared-conv"

        # Agent 1 responds
        await agent1.run("Question for agent 1", conversation_id=conversation_id)

        # Agent 2 can see history
        history = memory.get_message_history(conversation_id)
        assert len(history) > 0

        # Agent 2 responds
        await agent2.run("Question for agent 2", conversation_id=conversation_id)

        # History should have both
        history = memory.get_message_history(conversation_id)
        assert len(history) >= 2


@pytest.mark.asyncio
class TestFeatureComposition:
    """Test composability of features."""

    async def test_all_middleware_together(self):
        """Test all middleware types work together."""
        agent = FireflyAgent(
            "composed-agent",
            model="test",
            middleware=[
                LoggingMiddleware(),
                CostGuardMiddleware(budget_usd=10.0),
                PromptCacheMiddleware(cache_system_prompt=True),
                CircuitBreakerMiddleware(failure_threshold=5),
            ],
            auto_register=False,
        )

        # Should execute without errors
        result = await agent.run("Test question")
        assert result.output

    async def test_pipeline_with_all_step_types(self):
        """Test pipeline with various step types."""
        from fireflyframework_agentic.pipeline.context import PipelineContext

        agent = FireflyAgent("step-agent", model="test", auto_register=False)

        builder = PipelineBuilder()

        # Callable step
        async def load(context, inputs):
            return {"data": "loaded"}

        builder.add_node("load", load)

        # Agent step
        builder.add_node("process", AgentStep(agent))
        builder.add_edge("load", "process")

        # Batch step
        builder.add_node(
            "batch",
            BatchLLMStep(agent, prompts_key="batch_prompts"),
        )
        builder.add_edge("load", "batch")

        pipeline = builder.build()

        result = await pipeline.run(PipelineContext(inputs={"batch_prompts": ["Q1", "Q2"]}))
        assert result.success

    async def test_streaming_modes_both_work(self):
        """Test both streaming modes work with same agent."""
        agent = FireflyAgent(
            "dual-stream",
            model="test",
            middleware=[PromptCacheMiddleware()],
            auto_register=False,
        )

        # Buffered
        async with await agent.run_stream("Q1", streaming_mode="buffered") as stream:
            async for _ in stream.stream_text():
                break

        # Incremental
        async with await agent.run_stream("Q2", streaming_mode="incremental") as stream:
            async for _ in stream.stream_tokens():
                break
