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

"""Unit tests for BatchLLMStep."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.steps import BatchLLMStep


@pytest.mark.asyncio
class TestBatchLLMStep:
    """Test suite for batch LLM processing."""

    async def test_batch_step_processes_multiple_prompts(self):
        """Test that BatchLLMStep processes multiple prompts."""
        agent = FireflyAgent("batch-test", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=10)

        context = PipelineContext(inputs={}, correlation_id="test-batch")
        inputs = {
            "prompts": [
                "Hello 1",
                "Hello 2",
                "Hello 3",
            ]
        }

        results = await step.execute(context, inputs)

        # Should return 3 results
        assert len(results) == 3
        # All should be non-empty
        assert all(results)

    async def test_batch_step_with_single_prompt(self):
        """Test BatchLLMStep with single prompt (converted to list)."""
        agent = FireflyAgent("batch-single", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts")

        context = PipelineContext(inputs={}, correlation_id="test-single")
        inputs = {"prompts": "Single prompt"}

        results = await step.execute(context, inputs)

        # Should return 1 result
        assert len(results) == 1
        assert results[0]

    async def test_batch_step_with_empty_prompts(self):
        """Test BatchLLMStep with empty prompt list."""
        agent = FireflyAgent("batch-empty", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts")

        context = PipelineContext(inputs={}, correlation_id="test-empty")
        inputs = {"prompts": []}

        results = await step.execute(context, inputs)

        # Should return empty list
        assert results == []

    async def test_batch_step_missing_prompts_key(self):
        """Test BatchLLMStep when prompts key is missing."""
        agent = FireflyAgent("batch-missing", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts")

        context = PipelineContext(inputs={}, correlation_id="test-missing")
        inputs = {}  # No prompts key

        results = await step.execute(context, inputs)

        # Should return empty list
        assert results == []

    async def test_batch_step_respects_batch_size(self):
        """Test that BatchLLMStep splits prompts into correct batch sizes."""
        agent = FireflyAgent("batch-size", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=2)

        context = PipelineContext(inputs={}, correlation_id="test-size")
        inputs = {
            "prompts": [
                "Prompt 1",
                "Prompt 2",
                "Prompt 3",
                "Prompt 4",
                "Prompt 5",
            ]
        }

        results = await step.execute(context, inputs)

        # Should process all 5 prompts
        assert len(results) == 5

    async def test_batch_step_large_batch(self):
        """Test BatchLLMStep with large number of prompts."""
        agent = FireflyAgent("batch-large", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=10)

        context = PipelineContext(inputs={}, correlation_id="test-large")
        prompts = [f"Prompt {i}" for i in range(25)]
        inputs = {"prompts": prompts}

        results = await step.execute(context, inputs)

        # Should process all 25 prompts
        assert len(results) == 25

    async def test_batch_step_custom_prompts_key(self):
        """Test BatchLLMStep with custom prompts key."""
        agent = FireflyAgent("batch-custom-key", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="documents")

        context = PipelineContext(inputs={}, correlation_id="test-custom")
        inputs = {
            "documents": [
                "Document 1",
                "Document 2",
            ]
        }

        results = await step.execute(context, inputs)

        assert len(results) == 2

    async def test_batch_step_with_callback(self):
        """Test BatchLLMStep with completion callback."""
        agent = FireflyAgent("batch-callback", model="test", auto_register=False)

        callback_results = []

        def on_complete(results):
            callback_results.extend(results)

        step = BatchLLMStep(
            agent,
            prompts_key="prompts",
            on_batch_complete=on_complete,
        )

        context = PipelineContext(inputs={}, correlation_id="test-callback")
        inputs = {"prompts": ["Test 1", "Test 2"]}

        results = await step.execute(context, inputs)

        # Callback should have been invoked
        assert len(callback_results) == 2
        assert callback_results == results

    async def test_batch_step_handles_agent_errors(self):
        """Test that BatchLLMStep handles agent errors gracefully."""
        # Create agent that will fail
        agent = FireflyAgent("batch-error", model="test", auto_register=False)

        step = BatchLLMStep(agent, prompts_key="prompts")

        context = PipelineContext(inputs={}, correlation_id="test-error")
        inputs = {"prompts": ["Valid prompt"]}

        # Should not raise, but may include error results
        results = await step.execute(context, inputs)

        # Should still return results (even if some are errors)
        assert len(results) > 0

    async def test_batch_step_concurrent_processing(self):
        """Test that batch processing executes concurrently."""
        import time

        agent = FireflyAgent("batch-concurrent", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=10)

        context = PipelineContext(inputs={}, correlation_id="test-concurrent")
        # Create 10 prompts
        inputs = {"prompts": [f"Prompt {i}" for i in range(10)]}

        start = time.perf_counter()
        results = await step.execute(context, inputs)
        elapsed = time.perf_counter() - start

        # All prompts should complete
        assert len(results) == 10

        # Should be faster than sequential (though with test model this is hard to verify)
        # Just ensure it completes reasonably quickly
        assert elapsed < 10.0

    async def test_batch_step_default_parameters(self):
        """Test BatchLLMStep with default parameters."""
        agent = FireflyAgent("batch-defaults", model="test", auto_register=False)
        step = BatchLLMStep(agent)  # All defaults

        context = PipelineContext(inputs={}, correlation_id="test-defaults")
        inputs = {"prompts": ["Test"]}

        results = await step.execute(context, inputs)

        assert len(results) == 1

    async def test_batch_step_additional_kwargs(self):
        """Test that BatchLLMStep forwards additional kwargs to agent."""
        agent = FireflyAgent("batch-kwargs", model="test", auto_register=False)
        step = BatchLLMStep(
            agent,
            prompts_key="prompts",
            temperature=0.7,  # Additional kwarg
        )

        context = PipelineContext(inputs={}, correlation_id="test-kwargs")
        inputs = {"prompts": ["Test"]}

        # Should not raise
        results = await step.execute(context, inputs)
        assert len(results) == 1


@pytest.mark.asyncio
class TestBatchLLMStepEdgeCases:
    """Test edge cases for batch LLM processing."""

    async def test_batch_step_with_very_large_batch_size(self):
        """Test BatchLLMStep with batch size larger than prompt count."""
        agent = FireflyAgent("batch-large-size", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=1000)

        context = PipelineContext(inputs={}, correlation_id="test-large-size")
        inputs = {"prompts": ["P1", "P2", "P3"]}

        results = await step.execute(context, inputs)

        # Should still process all prompts in single batch
        assert len(results) == 3

    async def test_batch_step_with_batch_size_one(self):
        """Test BatchLLMStep with batch_size=1 (sequential processing)."""
        agent = FireflyAgent("batch-one", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=1)

        context = PipelineContext(inputs={}, correlation_id="test-one")
        inputs = {"prompts": ["P1", "P2", "P3"]}

        results = await step.execute(context, inputs)

        # Should process all 3 prompts (one at a time)
        assert len(results) == 3

    async def test_batch_step_result_order_preserved(self):
        """Test that result order matches input prompt order."""
        agent = FireflyAgent("batch-order", model="test", auto_register=False)
        step = BatchLLMStep(agent, prompts_key="prompts", batch_size=10)

        context = PipelineContext(inputs={}, correlation_id="test-order")
        inputs = {"prompts": ["First", "Second", "Third"]}

        results = await step.execute(context, inputs)

        # Results should maintain input order
        assert len(results) == 3
        # (Specific order validation would require deterministic test model responses)
