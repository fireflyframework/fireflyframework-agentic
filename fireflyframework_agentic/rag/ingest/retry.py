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

"""Retry helper for transient embedding-provider errors.

Wraps an embedder call with exponential backoff that respects the
``Retry-After`` HTTP header when the provider supplies it (Azure OpenAI
does on 429s). Retries on rate-limit (429), connection, timeout, and 5xx
errors. Non-retryable errors (4xx other than 429, validation errors,
etc.) propagate immediately on the first attempt.

Lives in the example package rather than the framework because the
framework's :class:`BaseEmbedder` records a ``max_retries`` setting but
does not actually loop on it (as of this writing).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag._telemetry import (
    embed_attempt_duration,
    embed_retries,
)

log = logging.getLogger(__name__)


class _EmbedFn(Protocol):
    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        raise NotImplementedError


_RETRYABLE_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "BadGatewayError",
        "ServiceUnavailableError",
        "GatewayTimeoutError",
    }
)

_RETRYABLE_MESSAGE_TOKENS: tuple[str, ...] = (
    "429",
    "rate limit",
    "too many requests",
    "503",
    "service unavailable",
    "502",
    "bad gateway",
    "504",
    "gateway timeout",
)


def _walk_causes(exc: BaseException):
    """Yield exc and every exception in its __cause__ / __context__ chain."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None and current.__context__ is not current.__cause__:
            stack.append(current.__context__)


def is_retryable(exc: BaseException) -> bool:
    """True if *exc* (or anything in its cause chain) looks like a transient
    rate-limit / connectivity error worth retrying.
    """
    for current in _walk_causes(exc):
        if type(current).__name__ in _RETRYABLE_TYPE_NAMES:
            return True
        status = getattr(current, "status_code", None)
        if isinstance(status, int) and (status == 429 or 500 <= status < 600):
            return True
        msg = str(current).lower()
        if any(token in msg for token in _RETRYABLE_MESSAGE_TOKENS):
            return True
    return False


def retry_after_seconds(exc: BaseException) -> float | None:
    """Extract the ``Retry-After`` header (in seconds) from any HTTP-like
    response object in the cause chain. Returns ``None`` if absent or
    unparseable.

    Supports both numeric (``Retry-After: 30``) and HTTP-date forms; only
    numeric is parsed here — HTTP-date is rare for rate-limit responses.

    Returns the **first** valid header value found while walking outward
    through ``__cause__`` / ``__context__``. SDKs that wrap a single
    ``Response`` (openai, anthropic) only carry one ``Retry-After``
    anywhere in the chain so this is not a problem in practice. If a
    future SDK chains multiple responses with different hints, the
    outermost wrapper wins — which is also typically the closest to the
    server's actual rate-limit signal.
    """
    for current in _walk_causes(exc):
        response = getattr(current, "response", None)
        if response is None:
            continue
        headers = getattr(response, "headers", None) or {}
        # case-insensitive lookup
        for key in ("retry-after", "Retry-After", "RETRY-AFTER"):
            value = headers.get(key) if hasattr(headers, "get") else None
            if value is None:
                continue
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                continue
            if seconds >= 0:
                return seconds
    return None


async def embed_with_retry(
    embedder: _EmbedFn,
    texts: list[str],
    *,
    max_attempts: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    sleep: Any = None,
) -> EmbeddingResult:
    """Call ``embedder.embed(texts)`` with exponential backoff on transient errors.

    Backoff schedule: ``initial_delay * (backoff_factor ** (attempt - 1))``
    capped at ``max_delay``. If the underlying error carries a
    ``Retry-After`` header that exceeds the computed delay, that value is
    used instead.

    ``sleep`` defaults to :func:`asyncio.sleep`; tests override it to
    avoid wall-clock waits.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    sleep_fn = sleep or asyncio.sleep
    delay = initial_delay
    last_exc: BaseException | None = None
    provider = type(embedder).__name__

    for attempt in range(1, max_attempts + 1):
        attempt_start = time.perf_counter()
        try:
            result = await embedder.embed(texts)
        except Exception as exc:
            last_exc = exc
            elapsed_ms = (time.perf_counter() - attempt_start) * 1000.0
            retryable = is_retryable(exc)
            if not retryable or attempt == max_attempts:
                outcome = "fatal"
                embed_attempt_duration.record(elapsed_ms, {"provider": provider, "outcome": outcome})
                embed_retries.add(1, {"provider": provider, "outcome": outcome})
                raise
            embed_attempt_duration.record(elapsed_ms, {"provider": provider, "outcome": "retry"})
            embed_retries.add(1, {"provider": provider, "outcome": "retry"})
            wait = retry_after_seconds(exc) or delay
            wait = min(wait, max_delay)
            log.warning(
                "embed attempt %d/%d failed (%s); retrying in %.1fs",
                attempt,
                max_attempts,
                type(exc).__name__,
                wait,
            )
            await sleep_fn(wait)
            delay = min(delay * backoff_factor, max_delay)
        else:
            elapsed_ms = (time.perf_counter() - attempt_start) * 1000.0
            embed_attempt_duration.record(elapsed_ms, {"provider": provider, "outcome": "ok"})
            return result

    # Unreachable: the loop either returns or raises.
    raise RuntimeError("retry loop terminated unexpectedly") from last_exc
