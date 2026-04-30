"""Tests for conversation memory summarization."""

from __future__ import annotations

from fireflyframework_agentic.memory.conversation import ConversationMemory
from fireflyframework_agentic.memory.types import ConversationTurn


class TestConversationSummarization:
    def test_summarizer_called_on_overflow(self) -> None:
        summaries: list[list[ConversationTurn]] = []

        def fake_summarizer(turns: list[ConversationTurn]) -> str:
            summaries.append(turns)
            return "Summary of evicted turns"

        mem = ConversationMemory(
            max_tokens=50,
            summarize_threshold=40,
            summarizer=fake_summarizer,
        )
        # TokenEstimator uses len(words) * 1.33, so ~40 words = ~53 tokens per turn
        words = " ".join(["word"] * 40)
        for _ in range(5):
            mem.add_turn("conv1", words, words, [])

        # Summarizer should have been called at least once
        assert len(summaries) >= 1

    def test_get_summary_returns_none_initially(self) -> None:
        mem = ConversationMemory()
        assert mem.get_summary("nonexistent") is None

    def test_get_summary_after_eviction(self) -> None:
        mem = ConversationMemory(
            max_tokens=30,
            summarize_threshold=20,
            summarizer=lambda turns: "evicted summary",
        )
        words = " ".join(["word"] * 30)
        for _ in range(5):
            mem.add_turn("c1", words, words, [])
        summary = mem.get_summary("c1")
        assert summary == "evicted summary"

    def test_no_summarizer_no_eviction(self) -> None:
        mem = ConversationMemory(max_tokens=30, summarize_threshold=20)
        words = " ".join(["word"] * 30)
        for _ in range(5):
            mem.add_turn("c1", words, words, [])
        assert mem.get_summary("c1") is None


class TestLLMSummarizer:
    def test_create_llm_summarizer_returns_callable(self) -> None:
        from fireflyframework_agentic.memory.summarization import create_llm_summarizer

        summarizer = create_llm_summarizer()
        assert callable(summarizer)

    def test_create_llm_summarizer_with_custom_model(self) -> None:
        from fireflyframework_agentic.memory.summarization import create_llm_summarizer

        summarizer = create_llm_summarizer(model="openai:gpt-4o-mini")
        assert callable(summarizer)
