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

"""Tests for ``embed_with_retry`` — exponential backoff on transient
embedding-provider errors. Uses a mock embedder that simulates Azure
OpenAI's 429 / Retry-After behaviour without any real network calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from examples.corpus_search.ingest.retry import (
    embed_with_retry,
    is_retryable,
    retry_after_seconds,
)
from fireflyframework_agentic.embeddings.types import EmbeddingResult

# --- Mocked exception types simulating openai SDK errors ---------------


class _MockResponse:
    """Mimics the ``response`` attr on openai SDK errors."""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class RateLimitError(Exception):
    """Mimics ``openai.RateLimitError`` (HTTP 429)."""

    def __init__(self, message: str = "429 Too Many Requests", retry_after: str | None = None) -> None:
        super().__init__(message)
        self.status_code = 429
        headers = {"retry-after": retry_after} if retry_after is not None else {}
        self.response = _MockResponse(status_code=429, headers=headers)


class APIConnectionError(Exception):
    """Mimics ``openai.APIConnectionError`` — network / DNS failure."""


class MockBadRequestError(Exception):
    """Mimics ``openai.BadRequestError`` (HTTP 400) — should NOT retry."""

    def __init__(self, message: str = "400 Bad Request") -> None:
        super().__init__(message)
        self.status_code = 400


# --- Mocked embedders --------------------------------------------------


class _Embedder:
    """Configurable mock embedder that records each call."""

    def __init__(self, *, fail_with: list[Exception] | None = None) -> None:
        # ``fail_with[i]`` is the exception to raise on the i-th call;
        # any further call returns a successful EmbeddingResult.
        self._fail_with = list(fail_with or [])
        self.call_count = 0
        self.received_texts: list[list[str]] = []

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        self.call_count += 1
        self.received_texts.append(list(texts))
        if self._fail_with:
            exc = self._fail_with.pop(0)
            raise exc
        return EmbeddingResult(
            embeddings=[[float(len(t)), 0.0, 0.0, 0.0] for t in texts],
            model="mock",
            usage=None,
            dimensions=4,
        )


# --- Sleep recorder ----------------------------------------------------


class _SleepRecorder:
    """Replacement for asyncio.sleep that records delays without waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


# --- Tests --------------------------------------------------------------


# is_retryable / retry_after_seconds helpers -----------------------------


def test_is_retryable_detects_rate_limit_error_class():
    assert is_retryable(RateLimitError()) is True


def test_is_retryable_detects_connection_error_class():
    assert is_retryable(APIConnectionError("dns failed")) is True


def test_is_retryable_detects_429_status_code():
    class _CustomError(Exception):
        status_code = 429
    assert is_retryable(_CustomError("rate limit")) is True


def test_is_retryable_detects_5xx_status_code():
    class _CustomError(Exception):
        status_code = 503
    assert is_retryable(_CustomError("service unavailable")) is True


def test_is_retryable_detects_429_in_message():
    assert is_retryable(RuntimeError("HTTP 429 Too Many Requests")) is True


def test_is_retryable_detects_through_cause_chain():
    """The framework wraps provider errors via ``raise X from exc`` —
    is_retryable should walk the cause chain.
    """
    inner = RateLimitError()
    try:
        try:
            raise inner
        except RateLimitError as exc:
            raise RuntimeError("Azure embedding failed") from exc
    except RuntimeError as wrapped:
        assert is_retryable(wrapped) is True


def test_is_retryable_returns_false_for_400_bad_request():
    assert is_retryable(MockBadRequestError("invalid input")) is False


def test_is_retryable_returns_false_for_value_error():
    assert is_retryable(ValueError("bad input")) is False


def test_retry_after_seconds_extracts_header():
    exc = RateLimitError(retry_after="30")
    assert retry_after_seconds(exc) == 30.0


def test_retry_after_seconds_returns_none_when_absent():
    exc = RateLimitError()  # no retry_after
    assert retry_after_seconds(exc) is None


def test_retry_after_seconds_returns_none_for_unparseable_header():
    exc = RateLimitError(retry_after="next-tuesday")
    assert retry_after_seconds(exc) is None


def test_retry_after_seconds_walks_cause_chain():
    inner = RateLimitError(retry_after="15")
    try:
        try:
            raise inner
        except RateLimitError as exc:
            raise RuntimeError("Azure embedding failed") from exc
    except RuntimeError as wrapped:
        assert retry_after_seconds(wrapped) == 15.0


# embed_with_retry — happy paths ----------------------------------------


async def test_embed_succeeds_first_try_no_retry():
    embedder = _Embedder()
    sleeper = _SleepRecorder()
    result = await embed_with_retry(embedder, ["hello"], sleep=sleeper)
    assert result.embeddings == [[5.0, 0.0, 0.0, 0.0]]
    assert embedder.call_count == 1
    assert sleeper.delays == []  # no retry, no sleep


async def test_embed_retries_on_429_and_succeeds():
    embedder = _Embedder(fail_with=[RateLimitError(), RateLimitError()])
    sleeper = _SleepRecorder()
    result = await embed_with_retry(
        embedder, ["t"], max_attempts=5, initial_delay=0.1, sleep=sleeper,
    )
    assert result.embeddings  # non-empty
    assert embedder.call_count == 3  # 2 failures + 1 success
    assert len(sleeper.delays) == 2


async def test_retry_uses_exponential_backoff():
    embedder = _Embedder(fail_with=[RateLimitError(), RateLimitError(), RateLimitError()])
    sleeper = _SleepRecorder()
    await embed_with_retry(
        embedder, ["t"],
        max_attempts=10,
        initial_delay=1.0,
        backoff_factor=2.0,
        max_delay=60.0,
        sleep=sleeper,
    )
    # Delays should be 1.0, 2.0, 4.0 (after 3 failures, 4th call succeeds)
    assert sleeper.delays == [1.0, 2.0, 4.0]


async def test_retry_caps_delay_at_max():
    embedder = _Embedder(fail_with=[RateLimitError()] * 4)
    sleeper = _SleepRecorder()
    await embed_with_retry(
        embedder, ["t"],
        max_attempts=10,
        initial_delay=10.0,
        backoff_factor=10.0,
        max_delay=15.0,
        sleep=sleeper,
    )
    # 10.0, 100->15 (capped), 150->15 (capped), 150->15 (capped)
    assert sleeper.delays == [10.0, 15.0, 15.0, 15.0]


async def test_retry_after_header_overrides_exponential_when_larger():
    """If the server says Retry-After: 30, we should sleep at least 30s
    even when the exponential schedule would say less.
    """
    embedder = _Embedder(fail_with=[RateLimitError(retry_after="30")])
    sleeper = _SleepRecorder()
    await embed_with_retry(
        embedder, ["t"],
        max_attempts=5,
        initial_delay=1.0,
        max_delay=60.0,
        sleep=sleeper,
    )
    # Server requested 30, exponential would have been 1.0
    assert sleeper.delays == [30.0]


async def test_retry_after_capped_at_max_delay():
    """Retry-After larger than max_delay is still capped — protection
    against absurd server values.
    """
    embedder = _Embedder(fail_with=[RateLimitError(retry_after="3600")])
    sleeper = _SleepRecorder()
    await embed_with_retry(
        embedder, ["t"], max_attempts=2, max_delay=60.0, sleep=sleeper,
    )
    assert sleeper.delays == [60.0]


# embed_with_retry — failure paths --------------------------------------


async def test_gives_up_after_max_attempts_and_raises_last_error():
    embedder = _Embedder(fail_with=[RateLimitError()] * 5)
    sleeper = _SleepRecorder()
    with pytest.raises(RateLimitError):
        await embed_with_retry(
            embedder, ["t"], max_attempts=3, initial_delay=0.01, sleep=sleeper,
        )
    assert embedder.call_count == 3
    assert len(sleeper.delays) == 2  # slept after attempt 1 and 2, not after 3


async def test_non_retryable_error_propagates_immediately():
    embedder = _Embedder(fail_with=[MockBadRequestError("invalid input")])
    sleeper = _SleepRecorder()
    with pytest.raises(MockBadRequestError):
        await embed_with_retry(embedder, ["t"], max_attempts=5, sleep=sleeper)
    assert embedder.call_count == 1
    assert sleeper.delays == []  # no retry attempted


async def test_value_error_not_retried():
    embedder = _Embedder(fail_with=[ValueError("bad shape")])
    sleeper = _SleepRecorder()
    with pytest.raises(ValueError):
        await embed_with_retry(embedder, ["t"], sleep=sleeper)
    assert embedder.call_count == 1


async def test_max_attempts_must_be_positive():
    embedder = _Embedder()
    with pytest.raises(ValueError, match="max_attempts"):
        await embed_with_retry(embedder, ["t"], max_attempts=0)


# embed_with_retry — input plumbing -------------------------------------


async def test_passes_texts_through_unchanged():
    embedder = _Embedder()
    sleeper = _SleepRecorder()
    await embed_with_retry(embedder, ["one", "two", "three"], sleep=sleeper)
    assert embedder.received_texts == [["one", "two", "three"]]


async def test_retries_pass_same_texts_each_time():
    embedder = _Embedder(fail_with=[RateLimitError(), RateLimitError()])
    sleeper = _SleepRecorder()
    await embed_with_retry(
        embedder, ["a", "b"], max_attempts=5, initial_delay=0.01, sleep=sleeper,
    )
    # Each retry sees the exact same input
    assert embedder.received_texts == [["a", "b"], ["a", "b"], ["a", "b"]]
