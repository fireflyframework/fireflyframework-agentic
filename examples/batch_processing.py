#!/usr/bin/env python3
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

"""Concurrent LLM requests, completion callbacks, and a classification pipeline.

Requires credentials for FIREFLY_AGENTIC_DEFAULT_MODEL (MODEL is a legacy
fallback). Running all demonstrations makes approximately 43 model requests.
BatchLLMStep uses bounded concurrency; it does not submit provider batch jobs
or guarantee a pricing discount.
"""

from __future__ import annotations

import asyncio
import os
import time

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.steps import BatchLLMStep


async def demo_basic_batch_processing():
    """Demonstrate basic batch processing of multiple prompts."""
    print("\n=== Basic Batch Processing Demo ===\n")

    agent = FireflyAgent(
        "classifier",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        instructions="You are a sentiment classifier. Respond with only: positive, negative, or neutral.",
        auto_register=False,
    )

    # Sample reviews to classify
    reviews = [
        "This product is amazing! I love it!",
        "Terrible quality, would not recommend.",
        "It's okay, nothing special.",
        "Best purchase I've ever made!",
        "Complete waste of money.",
    ]

    print(f"Processing {len(reviews)} reviews...")
    print()

    step = BatchLLMStep(
        agent,
        prompts_key="reviews",
        batch_size=10,  # Process up to 10 at once
    )

    from fireflyframework_agentic.pipeline.context import PipelineContext

    context = PipelineContext(inputs={}, correlation_id="batch-demo")
    inputs = {"reviews": reviews}

    start = time.perf_counter()
    results = await step.execute(context, inputs)
    elapsed = time.perf_counter() - start

    print(f"Results (processed in {elapsed:.2f}s):")
    for i, (review, sentiment) in enumerate(zip(reviews, results, strict=False), 1):
        print(f"{i}. '{review[:50]}...' → {sentiment}")

    print(f"\nProcessed {len(results)} reviews in {elapsed:.2f}s")
    print(f"Average: {elapsed / len(results):.2f}s per review")


async def demo_large_scale_batch():
    """Demonstrate large-scale batch processing."""
    print("\n\n=== Large-Scale Batch Processing Demo ===\n")

    agent = FireflyAgent(
        "summarizer",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        instructions="Summarize the following in 10 words or less.",
        auto_register=False,
    )

    # Generate sample documents
    num_documents = 20
    documents = [
        f"This is sample document number {i}. It contains important information "
        f"about topic {i} that needs to be processed and summarized."
        for i in range(1, num_documents + 1)
    ]

    print(f"Processing {len(documents)} documents in batches...")

    step = BatchLLMStep(
        agent,
        prompts_key="documents",
        batch_size=5,  # Process 5 at a time
    )

    from fireflyframework_agentic.pipeline.context import PipelineContext

    context = PipelineContext(inputs={}, correlation_id="large-batch")
    inputs = {"documents": documents}

    start = time.perf_counter()
    results = await step.execute(context, inputs)
    elapsed = time.perf_counter() - start

    print(f"\nProcessed {len(results)} documents in {elapsed:.2f}s")
    print(f"Average: {elapsed / len(results):.3f}s per document")
    print("\nSample results:")
    for i in range(min(5, len(results))):
        print(f"  {i + 1}. {results[i]}")
    if len(results) > 5:
        print(f"  ... ({len(results) - 5} more)")


async def demo_batch_with_callback():
    """Demonstrate batch processing with completion callback."""
    print("\n\n=== Batch Processing with Callback ===\n")

    agent = FireflyAgent(
        "extractor",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        instructions="Extract the main keyword from the text. Respond with just the keyword.",
        auto_register=False,
    )

    completed_batches = []

    def on_batch_complete(results):
        """Called when batch processing completes."""
        print(f"[Callback] Batch completed with {len(results)} results")
        completed_batches.append(results)

    texts = [
        "Python is a great programming language",
        "Machine learning is transforming industries",
        "Cloud computing enables scalability",
    ]

    step = BatchLLMStep(
        agent,
        prompts_key="texts",
        batch_size=10,
        on_batch_complete=on_batch_complete,
    )

    from fireflyframework_agentic.pipeline.context import PipelineContext

    context = PipelineContext(inputs={}, correlation_id="callback-demo")
    inputs = {"texts": texts}

    results = await step.execute(context, inputs)

    print("\nExtracted keywords:")
    for text, keyword in zip(texts, results, strict=False):
        print(f"  '{text[:40]}...' → {keyword}")

    print(f"\nCallback was invoked {len(completed_batches)} time(s)")


async def demo_batch_in_pipeline():
    """Demonstrate batch processing within a full pipeline."""
    print("\n\n=== Batch Processing in Pipeline ===\n")

    # Create a pipeline that:
    # 1. Loads documents
    # 2. Batch processes them for classification
    # 3. Aggregates results

    classifier_agent = FireflyAgent(
        "topic-classifier",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        instructions="Classify the topic. Respond with: technology, business, or other.",
        auto_register=False,
    )

    builder = PipelineBuilder()

    # Load step (normally would read from database/file)
    async def load_documents(context, inputs):
        return [
            "AI is revolutionizing software development",
            "Quarterly revenue exceeded expectations",
            "New smartphone features announced",
            "Market share continues to grow",
            "Climate change impacts discussed",
        ]

    builder.add_node("load", load_documents)

    # Batch classification step
    builder.add_node(
        "classify",
        BatchLLMStep(
            classifier_agent,
            prompts_key="load",
            batch_size=10,
        ),
    )

    # Aggregate step
    async def aggregate_results(context, inputs):
        classifications = context.get_node_result("classify").output
        counts = {}
        for classification in classifications:
            topic = str(classification).strip().lower()
            counts[topic] = counts.get(topic, 0) + 1
        return counts

    builder.add_node("aggregate", aggregate_results)
    builder.chain("load", "classify", "aggregate")

    # Build and run pipeline
    pipeline = builder.build()

    print("Running pipeline with batch processing...")
    result = await pipeline.run(inputs={})
    if not result.success:
        raise RuntimeError(result.error)

    print("\nPipeline result:")
    print(f"  Documents loaded: {len(result.outputs['load'].output)}")
    print(f"  Classifications: {result.outputs['classify'].output}")
    print(f"  Topic distribution: {result.final_output}")


async def demo_cost_comparison():
    """Demonstrate cost comparison: sequential vs batch."""
    print("\n\n=== Cost Comparison: Sequential vs Batch ===\n")

    from fireflyframework_agentic.observability.usage import default_usage_tracker

    agent = FireflyAgent(
        "cost-test",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        instructions="Say 'done'",
        auto_register=False,
    )

    prompts = ["Test 1", "Test 2", "Test 3", "Test 4", "Test 5"]

    # Sequential processing
    print("Testing sequential processing...")
    initial_cost = default_usage_tracker.get_summary().total_cost_usd

    for prompt in prompts:
        await agent.run(prompt)

    sequential_cost = default_usage_tracker.get_summary().total_cost_usd - initial_cost

    # Batch processing
    print("Testing batch processing...")
    initial_cost = default_usage_tracker.get_summary().total_cost_usd

    step = BatchLLMStep(agent, prompts_key="prompts")
    from fireflyframework_agentic.pipeline.context import PipelineContext

    context = PipelineContext(inputs={}, correlation_id="cost-test")
    await step.execute(context, {"prompts": prompts})

    batch_cost = default_usage_tracker.get_summary().total_cost_usd - initial_cost

    print("\nCost comparison:")
    print(f"  Sequential: ${sequential_cost:.6f}")
    print(f"  Batch:      ${batch_cost:.6f}")
    print(f"  Difference: ${abs(sequential_cost - batch_cost):.6f}")
    print()
    print("Costs are catalogue estimates for the selected model and observed token usage.")
    print("This demo uses concurrent processing, not provider batch APIs.")


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("Batch LLM Processing Demonstrations")
    print("=" * 70)

    # Run demonstrations
    await demo_basic_batch_processing()
    await demo_large_scale_batch()
    await demo_batch_with_callback()
    await demo_batch_in_pipeline()
    await demo_cost_comparison()

    # Summary
    print("\n\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print("\n✓ Batch processing enables cost-effective large-scale LLM usage")
    print("✓ Concurrent execution provides better throughput")
    print("✓ BatchLLMStep limits concurrent requests; provider batch discounts do not apply")
    print("✓ Ideal for non-real-time workloads")
    print("\nUsage:")
    print("  step = BatchLLMStep(")
    print("      agent=classifier_agent,")
    print("      prompts_key='documents',")
    print("      batch_size=50,")
    print("      on_batch_complete=callback_fn,")
    print("  )")
    print("\nBest Practices:")
    print("  - Use for non-time-sensitive workloads")
    print("  - Choose batch_size based on API limits and memory")
    print("  - Monitor costs with usage tracking")
    print("  - Consider provider-specific batch APIs for maximum savings")
    print()


if __name__ == "__main__":
    asyncio.run(main())
