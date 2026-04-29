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

"""Unit tests for incremental token-by-token streaming."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.agents.base import FireflyAgent


@pytest.mark.asyncio
class TestIncrementalStreaming:
    """Test suite for incremental streaming mode."""

    async def test_incremental_streaming_mode_parameter(self):
        """Test that streaming_mode parameter is accepted."""
        agent = FireflyAgent("test-incremental", model="test", auto_register=False)

        # Should not raise
        stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
        async with stream_ctx as stream:
            # Stream should have stream_tokens method
            assert hasattr(stream, "stream_tokens")

    async def test_buffered_streaming_mode_default(self):
        """Test that buffered mode is the default."""
        agent = FireflyAgent("test-buffered", model="test", auto_register=False)

        # Default should be buffered
        stream_ctx = await agent.run_stream("hello")
        async with stream_ctx as stream:
            # Should have standard streaming methods
            assert hasattr(stream, "stream_text")

    async def test_invalid_streaming_mode_raises(self):
        """Test that invalid streaming mode raises ValueError."""
        agent = FireflyAgent("test-invalid", model="test", auto_register=False)

        with pytest.raises(ValueError, match="Invalid streaming_mode"):
            await agent.run_stream("hello", streaming_mode="invalid")

    async def test_incremental_stream_has_stream_tokens(self):
        """Test that incremental stream provides stream_tokens() method."""
        agent = FireflyAgent("test-tokens", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
        async with stream_ctx as stream:
            assert callable(getattr(stream, "stream_tokens", None))

    async def test_incremental_stream_tokens_iteration(self):
        """Test that stream_tokens() can be iterated."""
        agent = FireflyAgent("test-iterate", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("Say hello", streaming_mode="incremental")
        async with stream_ctx as stream:
            tokens = []
            async for token in stream.stream_tokens():
                tokens.append(token)
                if len(tokens) >= 5:  # Limit iteration for testing
                    break

            # Should have received some tokens
            assert len(tokens) > 0

    async def test_incremental_stream_with_debounce(self):
        """Test incremental streaming with debounce parameter."""
        agent = FireflyAgent("test-debounce", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("Count to 10", streaming_mode="incremental")
        async with stream_ctx as stream:
            tokens = []
            # Use debounce to batch rapid tokens
            async for token in stream.stream_tokens(debounce_ms=10.0):
                tokens.append(token)
                if len(tokens) >= 3:
                    break

            assert len(tokens) > 0

    async def test_incremental_stream_delegates_other_methods(self):
        """Test that wrapper delegates non-streaming methods to underlying stream."""
        agent = FireflyAgent("test-delegate", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
        async with stream_ctx as stream:
            # Should still have access to underlying stream methods
            assert hasattr(stream, "stream_text")

    async def test_buffered_mode_uses_original_stream(self):
        """Test that buffered mode returns original stream behavior."""
        agent = FireflyAgent("test-buffered-orig", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("hello", streaming_mode="buffered")
        async with stream_ctx as stream:
            # Buffered mode doesn't add stream_tokens
            # (only incremental mode adds it)
            text_chunks = []
            async for chunk in stream.stream_text():
                text_chunks.append(chunk)
                if len(text_chunks) >= 3:
                    break

            assert len(text_chunks) > 0

    async def test_both_modes_record_usage(self):
        """Test that both streaming modes record usage after completion."""
        from fireflyframework_agentic.observability.usage import default_usage_tracker

        # Get initial summary
        initial_summary = default_usage_tracker.get_summary()
        initial_count = initial_summary.record_count

        # Test incremental mode - fully consume stream
        agent1 = FireflyAgent("test-usage-inc2", model="test", auto_register=False)
        stream_ctx1 = await agent1.run_stream("hello", streaming_mode="incremental")
        async with stream_ctx1 as stream:
            tokens = []
            async for token in stream.stream_tokens():
                tokens.append(token)
            # Stream fully consumed

        # Test buffered mode - fully consume stream
        agent2 = FireflyAgent("test-usage-buf2", model="test", auto_register=False)
        stream_ctx2 = await agent2.run_stream("hello", streaming_mode="buffered")
        async with stream_ctx2 as stream:
            chunks = []
            async for chunk in stream.stream_text():
                chunks.append(chunk)
            # Stream fully consumed

        # Both should have recorded usage
        final_summary = default_usage_tracker.get_summary()
        # At least 2 more records should have been added
        assert final_summary.record_count >= initial_count + 2

    async def test_incremental_mode_with_timeout(self):
        """Test that incremental streaming respects timeout parameter."""
        agent = FireflyAgent("test-timeout", model="test", auto_register=False)

        # This should work without timeout error for normal execution
        stream_ctx = await agent.run_stream("hello", streaming_mode="incremental", timeout=30.0)
        async with stream_ctx as stream:
            async for _token in stream.stream_tokens():
                break  # Just get first token

    async def test_middleware_fires_with_incremental_mode(self):
        """Test that incremental streaming works with middleware."""
        from fireflyframework_agentic.agents.builtin_middleware import LoggingMiddleware

        agent = FireflyAgent(
            "test-mw-inc2",
            model="test",
            middleware=[LoggingMiddleware()],
            auto_register=False,
        )

        # Should not raise with middleware present
        stream_ctx = await agent.run_stream("hello", streaming_mode="incremental")
        async with stream_ctx as stream:
            tokens = []
            async for token in stream.stream_tokens():
                tokens.append(token)

        # Just verify it worked
        assert len(tokens) > 0


@pytest.mark.asyncio
class TestIncrementalStreamingEdgeCases:
    """Test edge cases for incremental streaming."""

    async def test_empty_response_incremental(self):
        """Test incremental streaming with empty response."""
        agent = FireflyAgent("test-empty", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("Say nothing", streaming_mode="incremental")
        async with stream_ctx as stream:
            tokens = []
            async for token in stream.stream_tokens():
                tokens.append(token)

            # Empty response should yield no tokens (or empty tokens)
            # This depends on model behavior

    async def test_very_long_response_incremental(self):
        """Test incremental streaming with very long response."""
        agent = FireflyAgent("test-long", model="test", auto_register=False)

        stream_ctx = await agent.run_stream("Write a very long story", streaming_mode="incremental")
        async with stream_ctx as stream:
            token_count = 0
            async for _token in stream.stream_tokens():
                token_count += 1
                if token_count >= 100:  # Limit for testing
                    break

            # Should receive many tokens
            assert token_count > 0

    async def test_incremental_with_conversation_id(self):
        """Test incremental streaming with conversation memory."""
        from fireflyframework_agentic.memory.manager import MemoryManager

        memory = MemoryManager()
        agent = FireflyAgent("test-conv", model="test", memory=memory, auto_register=False)

        conv_id = "test-conv-123"

        stream_ctx = await agent.run_stream("hello", conversation_id=conv_id, streaming_mode="incremental")
        async with stream_ctx as stream:
            async for _ in stream.stream_tokens():
                break

        # Memory should be persisted (tested elsewhere, just ensure no error)
