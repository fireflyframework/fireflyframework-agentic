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

"""Measure buffered and incremental text streams for a configured model.

Set FIREFLY_AGENTIC_DEFAULT_MODEL and the provider credentials. Fragments can
contain multiple tokens; fragment counts are not billing-token counts. Results
depend on provider timing and network conditions, so no latency advantage is
guaranteed. All measured streams are consumed to completion.
"""

from __future__ import annotations

import asyncio
import os
import time

from fireflyframework_agentic.agents.base import FireflyAgent


def format_first_fragment(seconds: float | None) -> str:
    return "no text received" if seconds is None else f"{seconds * 1000:.1f}ms"


async def demo_buffered_streaming():
    """Demonstrate buffered streaming mode (default)."""
    print("\n=== Buffered Streaming Demo ===\n")
    print("Buffered mode streams in chunks/messages.")
    print("Text chunks arrive according to the provider and debounce settings.\n")

    agent = FireflyAgent(
        "buffered-demo",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        auto_register=False,
    )

    prompt = "Count from 1 to 5, saying each number on a new line."

    print(f"Prompt: {prompt}\n")
    print("Response (buffered):")

    start = time.perf_counter()
    first_chunk_time = None

    async with await agent.run_stream(prompt, streaming_mode="buffered") as stream:
        async for chunk in stream.stream_text(delta=True):
            if first_chunk_time is None:
                first_chunk_time = time.perf_counter() - start
                print(f"\n[First chunk received after {format_first_fragment(first_chunk_time)}]\n")

            print(chunk, end="", flush=True)

    total_time = time.perf_counter() - start
    print(f"\n\n[Total time: {total_time * 1000:.1f}ms]")
    print(f"[Time to first chunk: {format_first_fragment(first_chunk_time)}]")


async def demo_incremental_streaming():
    """Demonstrate incremental token-by-token streaming."""
    print("\n\n=== Incremental Streaming Demo ===\n")
    print("Incremental mode yields text fragments as they arrive.")
    print("Fragments can contain more than one model token.\n")

    agent = FireflyAgent(
        "incremental-demo",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
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
                print(f"\n[First token received after {format_first_fragment(first_token_time)}]\n")

            print(token, end="", flush=True)
            token_count += 1

    total_time = time.perf_counter() - start
    print(f"\n\n[Total time: {total_time * 1000:.1f}ms]")
    print(f"[Time to first token: {format_first_fragment(first_token_time)}]")
    print(f"[Total text fragments: {token_count}]")


async def demo_incremental_with_debounce():
    """Demonstrate incremental streaming with debouncing."""
    print("\n\n=== Incremental Streaming with Debounce ===\n")
    print("Debouncing batches rapid tokens together, reducing message frequency")
    print("while maintaining low latency. Useful for reducing network overhead.\n")

    agent = FireflyAgent(
        "debounce-demo",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
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
                print(f"\n[First batch after {format_first_fragment(first_token_time)}]\n")

            print(token_batch, end="", flush=True)
            batch_count += 1

    total_time = time.perf_counter() - start
    print(f"\n\n[Total time: {total_time * 1000:.1f}ms]")
    print(f"[Time to first batch: {format_first_fragment(first_token_time)}]")
    print(f"[Total batches: {batch_count}]")


async def demo_comparison():
    """Compare buffered vs incremental streaming side-by-side."""
    print("\n\n=== Side-by-Side Comparison ===\n")

    agent = FireflyAgent(
        "comparison-demo",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
        auto_register=False,
    )

    prompt = "Say hello"

    # Test buffered
    print("Testing buffered mode...")
    start_buf = time.perf_counter()
    ttft_buf = None

    async with await agent.run_stream(prompt, streaming_mode="buffered") as stream:
        async for _chunk in stream.stream_text(delta=True):
            if ttft_buf is None:
                ttft_buf = time.perf_counter() - start_buf

    total_buf = time.perf_counter() - start_buf

    # Test incremental
    print("Testing incremental mode...")
    start_inc = time.perf_counter()
    ttft_inc = None

    async with await agent.run_stream(prompt, streaming_mode="incremental") as stream:
        async for _token in stream.stream_tokens():
            if ttft_inc is None:
                ttft_inc = time.perf_counter() - start_inc

    total_inc = time.perf_counter() - start_inc

    # Show comparison
    print("\nResults:")
    print("  Buffered mode:")
    print(f"    - Time to first chunk: {format_first_fragment(ttft_buf)}")
    print(f"    - Total time: {total_buf * 1000:.1f}ms")
    print("\n  Incremental mode:")
    print(f"    - Time to first token: {format_first_fragment(ttft_inc)}")
    print(f"    - Total time: {total_inc * 1000:.1f}ms")

    if ttft_inc and ttft_buf:
        improvement = ((ttft_buf - ttft_inc) / ttft_buf) * 100
        print(f"\n  Observed relative difference in first-fragment latency: {improvement:.1f}%")


async def demo_interactive_chat():
    """Demonstrate incremental streaming in an interactive chat."""
    print("\n\n=== Interactive Chat with Incremental Streaming ===\n")
    print("This demo shows how incremental streaming feels in a real chatbot.")
    print("Responses appear token-by-token, just like ChatGPT.\n")

    agent = FireflyAgent(
        "chat-demo",
        model=os.getenv("FIREFLY_AGENTIC_DEFAULT_MODEL", os.getenv("MODEL", "openai-responses:gpt-6-luna")),
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
    print("\n✓ Both streaming modes deliver text progressively")
    print("✓ Better perceived performance for interactive applications")
    print("✓ Text fragment timing depends on the provider and network")
    print("✓ Ideal for chatbots, assistants, and live demos")
    print("\nUsage:")
    print("  # Incremental streaming")
    print("  async with await agent.run_stream(prompt, streaming_mode='incremental') as stream:")
    print("      async for token in stream.stream_tokens():")
    print("          print(token, end='', flush=True)")
    print("\n  # With debouncing to reduce message frequency")
    print("  async for token in stream.stream_tokens(debounce_ms=50.0):")
    print("      print(token, end='', flush=True)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
