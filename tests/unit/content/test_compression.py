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

"""Tests for content compression utilities."""

from fireflyframework_agentic.content.compression import (
    ContextCompressor,
    SlidingWindowManager,
    TokenEstimator,
    TruncationStrategy,
)


class TestTokenEstimator:
    def test_estimate_basic(self):
        estimator = TokenEstimator(tokens_per_word=1.0)
        assert estimator.estimate("one two three") == 3

    def test_estimate_default_ratio(self):
        estimator = TokenEstimator()
        result = estimator.estimate("hello world")
        assert result >= 2

    def test_fits(self):
        estimator = TokenEstimator(tokens_per_word=1.0)
        assert estimator.fits("one two three", 5) is True
        assert estimator.fits("one two three", 2) is False

    def test_empty_string(self):
        estimator = TokenEstimator()
        assert estimator.estimate("") == 1  # max(1, ...)


class TestTruncationStrategy:
    async def test_no_truncation_needed(self):
        strategy = TruncationStrategy(tokens_per_word=1.0)
        result = await strategy.compress("short text", 100)
        assert result == "short text"

    async def test_truncation_applied(self):
        text = " ".join(f"word{i}" for i in range(100))
        strategy = TruncationStrategy(tokens_per_word=1.0)
        result = await strategy.compress(text, 10)
        assert "[... truncated ...]" in result
        assert len(result.split()) < 100


class TestContextCompressor:
    async def test_no_compression_when_fits(self):
        strategy = TruncationStrategy(tokens_per_word=1.0)
        compressor = ContextCompressor(strategy, estimator=TokenEstimator(tokens_per_word=1.0))
        result = await compressor.compress("short text", 100)
        assert result == "short text"

    async def test_compression_applied_when_exceeds(self):
        text = " ".join(f"word{i}" for i in range(100))
        strategy = TruncationStrategy(tokens_per_word=1.0)
        compressor = ContextCompressor(strategy, estimator=TokenEstimator(tokens_per_word=1.0))
        result = await compressor.compress(text, 10)
        assert "[... truncated ...]" in result


class TestSlidingWindowManager:
    def test_add_and_get(self):
        mgr = SlidingWindowManager(max_tokens=1000)
        mgr.add("segment one")
        mgr.add("segment two")
        ctx = mgr.get_context()
        assert "segment one" in ctx
        assert "segment two" in ctx
        assert mgr.segment_count == 2

    def test_eviction(self):
        mgr = SlidingWindowManager(
            max_tokens=5,
            estimator=TokenEstimator(tokens_per_word=1.0),
        )
        mgr.add("word1 word2 word3")
        mgr.add("word4 word5 word6")
        # Should evict oldest to stay within budget
        assert mgr.segment_count <= 2

    def test_clear(self):
        mgr = SlidingWindowManager()
        mgr.add("test")
        mgr.clear()
        assert mgr.segment_count == 0
        assert mgr.get_context() == ""
