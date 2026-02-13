#!/usr/bin/env python3
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

"""Example demonstrating batch LLM processing for cost optimization.

Batch processing allows processing multiple prompts concurrently or through
provider batch APIs (when available), providing significant benefits:

Benefits:
    - Cost savings: Up to 50% discount with provider batch APIs
    - Higher throughput: Process hundreds/thousands of prompts efficiently
    - Resource optimization: Better utilization of API quotas
    - Ideal for non-real-time workloads

Use Cases:
    - Bulk document classification
    - Large-scale sentiment analysis
    - Data extraction from thousands of documents
    - Batch translation tasks
    - Content generation pipelines
"""

from __future__ import annotations

import asyncio
import os
import time

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.steps import BatchLLMStep


async def demo_basic_batch_processing():
    """Demonstrate basic batch processing of multiple prompts."""
    print("\n=== Basic Batch Processing Demo ===\n")

    agent = FireflyAgent(
        "classifier",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
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

    from fireflyframework_genai.pipeline.context import PipelineContext

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
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
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

    from fireflyframework_genai.pipeline.context import PipelineContext

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
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
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

    from fireflyframework_genai.pipeline.context import PipelineContext

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
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        instructions="Classify the topic. Respond with: technology, business, or other.",
        auto_register=False,
    )

    builder = PipelineBuilder()

    # Load step (normally would read from database/file)
    async def load_documents(context, inputs):
        return {
            "documents": [
                "AI is revolutionizing software development",
                "Quarterly revenue exceeded expectations",
                "New smartphone features announced",
                "Market share continues to grow",
                "Climate change impacts discussed",
            ]
        }

    builder.add_node("load", load_documents)

    # Batch classification step
    builder.add_node(
        "classify",
        BatchLLMStep(
            classifier_agent,
            prompts_key="documents",
            batch_size=10,
        ),
        depends_on=["load"],
    )

    # Aggregate step
    async def aggregate_results(context, inputs):
        classifications = inputs.get("classify", [])
        counts = {}
        for classification in classifications:
            topic = str(classification).strip().lower()
            counts[topic] = counts.get(topic, 0) + 1
        return counts

    builder.add_node("aggregate", aggregate_results, depends_on=["classify"])

    # Build and run pipeline
    pipeline = builder.build()

    print("Running pipeline with batch processing...")
    result = await pipeline.run({})

    print("\nPipeline result:")
    print(f"  Documents loaded: {len(result.get_node_result('load')['documents'])}")
    print(f"  Classifications: {result.get_node_result('classify')}")
    print(f"  Topic distribution: {result.output}")


async def demo_cost_comparison():
    """Demonstrate cost comparison: sequential vs batch."""
    print("\n\n=== Cost Comparison: Sequential vs Batch ===\n")

    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Skipping cost comparison (requires OPENAI_API_KEY)")
        return

    from fireflyframework_genai.observability.usage import default_usage_tracker

    agent = FireflyAgent(
        "cost-test",
        model="openai:gpt-4o-mini",
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
    from fireflyframework_genai.pipeline.context import PipelineContext

    context = PipelineContext(inputs={}, correlation_id="cost-test")
    await step.execute(context, {"prompts": prompts})

    batch_cost = default_usage_tracker.get_summary().total_cost_usd - initial_cost

    print("\nCost comparison:")
    print(f"  Sequential: ${sequential_cost:.6f}")
    print(f"  Batch:      ${batch_cost:.6f}")
    print(f"  Difference: ${abs(sequential_cost - batch_cost):.6f}")
    print()
    print("Note: True batch APIs (when available) can provide up to 50% cost savings.")
    print("This demo uses concurrent processing, not provider batch APIs.")


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("Batch LLM Processing Demonstrations")
    print("=" * 70)

    if not os.getenv("OPENAI_API_KEY"):
        print("\n⚠️  Warning: OPENAI_API_KEY not set.")
        print("These demos require a real LLM to show batch processing benefits.")
        print("\nTo run with OpenAI:")
        print("  export OPENAI_API_KEY=your-key-here")
        print("  python examples/batch_processing.py")
        return

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
    print("✓ Provider batch APIs can offer up to 50% cost savings")
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
