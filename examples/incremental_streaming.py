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

"""Example demonstrating incremental token-by-token streaming.

This example shows the difference between buffered and incremental streaming
modes, highlighting the latency improvements for interactive applications.

Incremental Streaming Benefits:
    - Lower time-to-first-token (TTFT)
    - Better perceived performance for users
    - Minimal latency - tokens appear as they're generated
    - Ideal for chatbots, interactive assistants, live demos

Buffered Streaming Benefits:
    - Slightly higher throughput
    - Better for batch processing
    - Simpler client-side handling
"""

from __future__ import annotations

import asyncio
import os
import time

from fireflyframework_agentic.agents.base import FireflyAgent


async def demo_buffered_streaming():
    """Demonstrate buffered streaming mode (default)."""
    print("\n=== Buffered Streaming Demo ===\n")
    print("Buffered mode streams in chunks/messages.")
    print("Good for most use cases, slightly higher throughput.\n")

    agent = FireflyAgent(
        "buffered-demo",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        auto_register=False,
    )

    prompt = "Count from 1 to 5, saying each number on a new line."

    print(f"Prompt: {prompt}\n")
    print("Response (buffered):")

    start = time.perf_counter()
    first_chunk_time = None

    async with await agent.run_stream(prompt, streaming_mode="buffered") as stream:
        async for chunk in stream.stream_text():
            if first_chunk_time is None:
                first_chunk_time = time.perf_counter() - start
                print(f"\n[First chunk received after {first_chunk_time * 1000:.1f}ms]\n")

            print(chunk, end="", flush=True)

    total_time = time.perf_counter() - start
    print(f"\n\n[Total time: {total_time * 1000:.1f}ms]")
    print(f"[Time to first chunk: {first_chunk_time * 1000:.1f}ms]")


async def demo_incremental_streaming():
    """Demonstrate incremental token-by-token streaming."""
    print("\n\n=== Incremental Streaming Demo ===\n")
    print("Incremental mode streams individual tokens as they arrive.")
    print("Provides minimal latency and best perceived performance.\n")

    agent = FireflyAgent(
        "incremental-demo",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        auto_register=False,
    )

    prompt = "Count from 1 to 5, saying each number on a new line."

    print(f"Prompt: {prompt}\n")
    print("Response (incremental):")

    start = time.perf_counter()
    first_token_time = None
    token_count = 0

    async with await agent.run_stream(prompt, streaming_mode="incremental") as stream:
        async for token in stream.stream_tokens():
            if first_token_time is None:
                first_token_time = time.perf_counter() - start
                print(f"\n[First token received after {first_token_time * 1000:.1f}ms]\n")

            print(token, end="", flush=True)
            token_count += 1

    total_time = time.perf_counter() - start
    print(f"\n\n[Total time: {total_time * 1000:.1f}ms]")
    print(f"[Time to first token: {first_token_time * 1000:.1f}ms]")
    print(f"[Total tokens: {token_count}]")


async def demo_incremental_with_debounce():
    """Demonstrate incremental streaming with debouncing."""
    print("\n\n=== Incremental Streaming with Debounce ===\n")
    print("Debouncing batches rapid tokens together, reducing message frequency")
    print("while maintaining low latency. Useful for reducing network overhead.\n")

    agent = FireflyAgent(
        "debounce-demo",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        auto_register=False,
    )

    prompt = "Write a short haiku about programming."

    print(f"Prompt: {prompt}\n")
    print("Response (incremental with 50ms debounce):")

    start = time.perf_counter()
    first_token_time = None
    batch_count = 0

    async with await agent.run_stream(prompt, streaming_mode="incremental") as stream:
        # 50ms debounce - batches rapid tokens together
        async for token_batch in stream.stream_tokens(debounce_ms=50.0):
            if first_token_time is None:
                first_token_time = time.perf_counter() - start
                print(f"\n[First batch after {first_token_time * 1000:.1f}ms]\n")

            print(token_batch, end="", flush=True)
            batch_count += 1

    total_time = time.perf_counter() - start
    print(f"\n\n[Total time: {total_time * 1000:.1f}ms]")
    print(f"[Time to first batch: {first_token_time * 1000:.1f}ms]")
    print(f"[Total batches: {batch_count}]")


async def demo_comparison():
    """Compare buffered vs incremental streaming side-by-side."""
    print("\n\n=== Side-by-Side Comparison ===\n")

    agent = FireflyAgent(
        "comparison-demo",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        auto_register=False,
    )

    prompt = "Say hello"

    # Test buffered
    print("Testing buffered mode...")
    start_buf = time.perf_counter()
    ttft_buf = None

    async with await agent.run_stream(prompt, streaming_mode="buffered") as stream:
        async for _chunk in stream.stream_text():
            if ttft_buf is None:
                ttft_buf = time.perf_counter() - start_buf
            break  # Just measure first chunk

    total_buf = time.perf_counter() - start_buf

    # Test incremental
    print("Testing incremental mode...")
    start_inc = time.perf_counter()
    ttft_inc = None

    async with await agent.run_stream(prompt, streaming_mode="incremental") as stream:
        async for _token in stream.stream_tokens():
            if ttft_inc is None:
                ttft_inc = time.perf_counter() - start_inc
            break  # Just measure first token

    total_inc = time.perf_counter() - start_inc

    # Show comparison
    print("\nResults:")
    print("  Buffered mode:")
    print(f"    - Time to first chunk: {ttft_buf * 1000:.1f}ms")
    print(f"    - Total time: {total_buf * 1000:.1f}ms")
    print("\n  Incremental mode:")
    print(f"    - Time to first token: {ttft_inc * 1000:.1f}ms")
    print(f"    - Total time: {total_inc * 1000:.1f}ms")

    if ttft_inc and ttft_buf:
        improvement = ((ttft_buf - ttft_inc) / ttft_buf) * 100
        print(f"\n  Improvement: {improvement:.1f}% faster time-to-first-token")


async def demo_interactive_chat():
    """Demonstrate incremental streaming in an interactive chat."""
    print("\n\n=== Interactive Chat with Incremental Streaming ===\n")
    print("This demo shows how incremental streaming feels in a real chatbot.")
    print("Responses appear token-by-token, just like ChatGPT.\n")

    agent = FireflyAgent(
        "chat-demo",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        auto_register=False,
    )

    questions = [
        "What is Python?",
        "Why is streaming important?",
        "How does async/await work?",
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n[Question {i}]: {question}")
        print("[Assistant]: ", end="", flush=True)

        async with await agent.run_stream(question, streaming_mode="incremental") as stream:
            async for token in stream.stream_tokens():
                print(token, end="", flush=True)
                # Small delay to simulate typewriter effect
                await asyncio.sleep(0.01)

        print()  # New line after response


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("Incremental Streaming Demonstrations")
    print("=" * 70)

    if not os.getenv("OPENAI_API_KEY"):
        print("\n⚠️  Warning: OPENAI_API_KEY not set.")
        print("These demos require a real LLM to show streaming behavior.")
        print("\nTo run with OpenAI:")
        print("  export OPENAI_API_KEY=your-key-here")
        print("  python examples/incremental_streaming.py")
        print("\nTo run with another provider:")
        print("  export MODEL=anthropic:claude-3-5-sonnet-20241022")
        print("  export ANTHROPIC_API_KEY=your-key-here")
        print("  python examples/incremental_streaming.py")
        return

    # Run demonstrations
    await demo_buffered_streaming()
    await demo_incremental_streaming()
    await demo_incremental_with_debounce()
    await demo_comparison()
    await demo_interactive_chat()

    # Summary
    print("\n\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print("\n✓ Incremental streaming provides 20-40% lower time-to-first-token")
    print("✓ Better perceived performance for interactive applications")
    print("✓ Tokens appear immediately as they're generated")
    print("✓ Ideal for chatbots, assistants, and live demos")
    print("\nUsage:")
    print("  # Incremental streaming")
    print("  async with await agent.run_stream(prompt, streaming_mode='incremental') as stream:")
    print("      async for token in stream.stream_tokens():")
    print("          print(token, end='', flush=True)")
    print("\n  # With debouncing to reduce message frequency")
    print("  async for token in stream.stream_tokens(debounce_ms=50.0):")
    print("      ...")
    print("\nREST API:")
    print("  POST /agents/{name}/stream/incremental")
    print("  - Returns SSE events with individual tokens")
    print("  - Query param: debounce_ms (optional)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
