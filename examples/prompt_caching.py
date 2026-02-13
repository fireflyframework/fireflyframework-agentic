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

"""Example demonstrating provider prompt caching for cost optimization.

Prompt caching allows providers to cache portions of prompts (system prompts,
long contexts, few-shot examples) and reuse them across requests.

Benefits:
    - 90-95% cost reduction on cached tokens
    - Reduced latency (no reprocessing of cached content)
    - Better throughput

Supported Providers:
    - Anthropic Claude (prompt caching API)
    - OpenAI (automatic caching in supported models)
    - Gemini (context caching API)

Example Savings:
    - System prompt: 10,000 tokens
    - Without caching: 100 requests × $0.03 = $3.00
    - With caching: $0.03 + 99 × $0.003 = $0.327
    - Savings: $2.67 (89% cost reduction)
"""

from __future__ import annotations

import asyncio
import os

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.agents.prompt_cache import CacheStatistics, PromptCacheMiddleware

# Sample long system prompt that would benefit from caching
LEGAL_ASSISTANT_PROMPT = (
    """You are an expert legal assistant specializing in contract analysis.

Your expertise includes:
- Contract law and interpretation
- Risk identification and assessment
- Compliance verification
- Legal terminology and definitions

When analyzing contracts, you should:
1. Identify key terms and conditions
2. Highlight potential risks or unusual clauses
3. Verify standard legal protections
4. Note any missing standard clauses
5. Summarize obligations for each party

Standard contract elements to review:
- Parties and effective dates
- Scope of services/products
- Payment terms and schedules
- Termination conditions
- Liability and indemnification clauses
- Intellectual property rights
- Confidentiality provisions
- Dispute resolution mechanisms
- Force majeure clauses
- Governing law and jurisdiction

Always provide clear, actionable analysis that non-legal stakeholders can understand.

For questions about specific contract sections, provide detailed analysis with
references to relevant legal principles and potential implications.

"""
    * 10
)  # Repeat to create a ~5000 token system prompt


async def demo_without_caching():
    """Demonstrate cost without prompt caching."""
    print("\n=== Demonstration WITHOUT Prompt Caching ===\n")

    agent = FireflyAgent(
        "legal-no-cache",
        model=os.getenv("MODEL", "anthropic:claude-3-5-sonnet-20241022"),
        instructions=LEGAL_ASSISTANT_PROMPT,
        auto_register=False,
        # No caching middleware
    )

    questions = [
        "What are standard termination clauses?",
        "Explain indemnification provisions.",
        "What is force majeure?",
    ]

    print(f"System prompt length: ~{len(LEGAL_ASSISTANT_PROMPT.split())} words")
    print(f"Processing {len(questions)} questions without caching...\n")

    from fireflyframework_genai.observability.usage import default_usage_tracker

    initial_cost = default_usage_tracker.get_summary().total_cost_usd

    for i, question in enumerate(questions, 1):
        print(f"Question {i}: {question}")
        result = await agent.run(question)
        print(f"Answer: {str(result.output)[:100]}...")
        print()

    final_cost = default_usage_tracker.get_summary().total_cost_usd
    total_cost = final_cost - initial_cost

    print(f"Total cost WITHOUT caching: ${total_cost:.6f}")
    print("(System prompt is reprocessed for each request)")


async def demo_with_caching():
    """Demonstrate cost savings with prompt caching."""
    print("\n\n=== Demonstration WITH Prompt Caching ===\n")

    cache_stats = CacheStatistics()

    agent = FireflyAgent(
        "legal-cached",
        model=os.getenv("MODEL", "anthropic:claude-3-5-sonnet-20241022"),
        instructions=LEGAL_ASSISTANT_PROMPT,
        middleware=[
            PromptCacheMiddleware(
                cache_system_prompt=True,
                cache_min_tokens=1024,
            ),
        ],
        auto_register=False,
    )

    questions = [
        "What are standard termination clauses?",
        "Explain indemnification provisions.",
        "What is force majeure?",
    ]

    print(f"System prompt length: ~{len(LEGAL_ASSISTANT_PROMPT.split())} words")
    print(f"Processing {len(questions)} questions with caching...\n")

    from fireflyframework_genai.observability.usage import default_usage_tracker

    initial_cost = default_usage_tracker.get_summary().total_cost_usd

    for i, question in enumerate(questions, 1):
        print(f"Question {i}: {question}")
        result = await agent.run(question)

        # Record cache usage
        if hasattr(result, "usage") and callable(result.usage):
            usage = result.usage()
            cache_creation = getattr(usage, "cache_creation_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_tokens", 0) or 0
            cache_stats.record_usage(cache_creation, cache_read)

            if cache_creation > 0:
                print(f"  → Cache MISS (created {cache_creation} token cache)")
            elif cache_read > 0:
                print(f"  → Cache HIT (read {cache_read} cached tokens)")

        print(f"Answer: {str(result.output)[:100]}...")
        print()

    final_cost = default_usage_tracker.get_summary().total_cost_usd
    total_cost = final_cost - initial_cost

    print(f"Total cost WITH caching: ${total_cost:.6f}")
    print(f"Cache hit rate: {cache_stats.cache_hit_rate():.1%}")
    print(f"Estimated savings: ${cache_stats.estimated_savings_usd():.6f}")


async def demo_cache_statistics():
    """Demonstrate cache statistics tracking."""
    print("\n\n=== Cache Statistics Demonstration ===\n")

    stats = CacheStatistics()

    # Simulate cache usage pattern
    print("Simulating 10 requests with caching:\n")

    # First request: cache miss (creation)
    print("Request 1: Cache MISS - Creating cache (10,000 tokens)")
    stats.record_usage(cache_creation_tokens=10000, cache_read_tokens=0)

    # Next 9 requests: cache hits
    for i in range(2, 11):
        print(f"Request {i}: Cache HIT - Reading from cache (10,000 tokens)")
        stats.record_usage(cache_creation_tokens=0, cache_read_tokens=10000)

    print(f"\n{'-' * 60}")
    print("Cache Statistics Summary:")
    print(f"{'-' * 60}")

    summary = stats.summary()
    print(f"Total requests: {summary['total_requests']}")
    print(f"Cache hits: {summary['cache_hits']}")
    print(f"Cache hit rate: {summary['cache_hit_rate']:.1%}")
    print(f"Total cache creation tokens: {summary['total_cache_creation_tokens']:,}")
    print(f"Total cache read tokens: {summary['total_cache_read_tokens']:,}")
    print(f"Estimated savings: ${summary['estimated_savings_usd']:.2f}")

    print(f"\n{'-' * 60}")
    print("Cost Breakdown:")
    print(f"{'-' * 60}")

    # Calculate detailed cost breakdown
    input_cost_per_1k = 3.00 / 1000  # $3 per 1M input tokens for Sonnet
    cache_read_cost_per_1k = 0.30 / 1000  # $0.30 per 1M cached tokens

    without_cache = 100000 * input_cost_per_1k  # 10 requests × 10k tokens
    cache_creation = 10000 * input_cost_per_1k
    cache_reads = 90000 * cache_read_cost_per_1k
    with_cache = cache_creation + cache_reads

    print("Without caching:")
    print(f"  100,000 tokens @ ${input_cost_per_1k * 1000:.2f}/1M = ${without_cache:.3f}")
    print("\nWith caching:")
    print(f"  Cache creation: 10,000 tokens @ ${input_cost_per_1k * 1000:.2f}/1M = ${cache_creation:.3f}")
    print(f"  Cache reads: 90,000 tokens @ ${cache_read_cost_per_1k * 1000:.2f}/1M = ${cache_reads:.3f}")
    print(f"  Total: ${with_cache:.3f}")
    print(
        f"\nSavings: ${without_cache - with_cache:.3f} ({((without_cache - with_cache) / without_cache * 100):.1f}% reduction)"
    )


async def demo_best_practices():
    """Demonstrate best practices for prompt caching."""
    print("\n\n=== Prompt Caching Best Practices ===\n")

    print("1. WHEN TO USE PROMPT CACHING:")
    print("   ✓ System prompts > 1024 tokens")
    print("   ✓ Repeated questions with same context")
    print("   ✓ Document Q&A with long documents")
    print("   ✓ Few-shot examples (same examples, different inputs)")
    print()

    print("2. WHEN NOT TO USE PROMPT CACHING:")
    print("   ✗ Short system prompts (< 1024 tokens)")
    print("   ✗ One-off requests")
    print("   ✗ Frequently changing contexts")
    print("   ✗ Real-time pricing (check provider docs)")
    print()

    print("3. CONFIGURATION RECOMMENDATIONS:")
    print("   • cache_min_tokens: 1024 (Anthropic minimum)")
    print("   • cache_ttl_seconds: 300 (5 minutes, auto-extended)")
    print("   • Enable for document Q&A, customer support, legal analysis")
    print()

    print("4. COST OPTIMIZATION STRATEGIES:")
    print("   • Batch similar queries within cache TTL window")
    print("   • Structure prompts to maximize cacheable content")
    print("   • Monitor cache hit rates and adjust strategy")
    print("   • Use CacheStatistics to track savings")
    print()

    print("5. EXAMPLE USE CASES:")
    print("   • Legal document analysis (long system prompts)")
    print("   • Customer support chatbots (consistent personality/rules)")
    print("   • Document Q&A (cache document context)")
    print("   • Code review assistants (cache coding standards)")
    print()


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("Provider Prompt Caching Demonstrations")
    print("=" * 70)

    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        print("\n⚠️  Warning: No API keys set.")
        print("For full demonstrations with real cost savings:")
        print()
        print("Anthropic (recommended for prompt caching demo):")
        print("  export ANTHROPIC_API_KEY=your-key-here")
        print("  export MODEL=anthropic:claude-3-5-sonnet-20241022")
        print()
        print("OpenAI:")
        print("  export OPENAI_API_KEY=your-key-here")
        print("  export MODEL=openai:gpt-4o")
        print()

        # Run statistics demo (doesn't need API)
        await demo_cache_statistics()
        await demo_best_practices()
        return

    # Run full demonstrations
    await demo_without_caching()
    await demo_with_caching()
    await demo_cache_statistics()
    await demo_best_practices()

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print("\n✓ Prompt caching provides 90-95% cost reduction on cached tokens")
    print("✓ Ideal for long system prompts and repeated contexts")
    print("✓ Reduces latency by avoiding reprocessing")
    print("✓ Works best with >1024 token cacheable content")
    print("\nUsage:")
    print("  from fireflyframework_genai.agents.prompt_cache import PromptCacheMiddleware")
    print()
    print("  agent = FireflyAgent(")
    print("      'assistant',")
    print("      model='anthropic:claude-3-5-sonnet-20241022',")
    print("      instructions=long_system_prompt,  # Will be cached")
    print("      middleware=[PromptCacheMiddleware()],")
    print("  )")
    print()


if __name__ == "__main__":
    asyncio.run(main())
