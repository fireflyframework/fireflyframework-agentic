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

"""Caching wrapper for deterministic tools.

:class:`CachedTool` wraps any :class:`~fireflyframework_agentic.tools.base.ToolProtocol`
implementation and transparently memoises results using a TTL-based
in-memory cache keyed on the tool's input arguments.

Usage::

    from fireflyframework_agentic.tools.cached import CachedTool

    cached = CachedTool(my_slow_tool, ttl_seconds=300.0)
    result = await cached.execute(query="hello")   # calls underlying tool
    result2 = await cached.execute(query="hello")  # cache hit
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from fireflyframework_agentic.tools.base import ToolProtocol

logger = logging.getLogger(__name__)


class _CacheEntry:
    """Internal: a single cached result with an expiry timestamp."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at


class CachedTool:
    """Caching decorator for any :class:`ToolProtocol` implementation.

    Concurrent identical misses are **single-flighted**: the first caller runs
    the underlying tool while the others await the same result, so an expensive
    or rate-limited tool is not stampeded. Intended for use on one event loop.

    Parameters:
        tool: The underlying tool to wrap.
        ttl_seconds: Time-to-live in seconds for cached entries.
            Pass ``0`` or a negative value to disable caching (pass-through).
        max_entries: Maximum number of cached entries.  When exceeded, the
            oldest entry is evicted (FIFO).
    """

    def __init__(
        self,
        tool: ToolProtocol,
        *,
        ttl_seconds: float = 300.0,
        max_entries: int = 1024,
    ) -> None:
        self._tool = tool
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    # -- ToolProtocol conformance --------------------------------------------

    @property
    def name(self) -> str:
        return self._tool.name

    @property
    def description(self) -> str:
        return self._tool.description

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool, returning a cached result when available.

        A fresh entry is served from cache. On a miss, the first caller for a
        key computes the result while concurrent callers await the same future
        (single-flight), so the underlying tool runs once per key.
        """
        if self._ttl <= 0:
            return await self._tool.execute(**kwargs)

        key = self._make_key(kwargs)

        async with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.expires_at > time.monotonic():
                logger.debug("Cache hit for tool '%s' (key=%s)", self.name, key[:12])
                return entry.value
            inflight = self._inflight.get(key)
            is_leader = inflight is None
            if is_leader:
                inflight = asyncio.get_running_loop().create_future()
                self._inflight[key] = inflight

        if not is_leader:
            return await inflight  # a concurrent miss is already computing this key

        try:
            result = await self._tool.execute(**kwargs)
        except BaseException as exc:
            async with self._lock:
                self._inflight.pop(key, None)
            if not inflight.done():
                inflight.set_exception(exc)
            raise
        async with self._lock:
            self._put(key, result, time.monotonic())
            self._inflight.pop(key, None)
        if not inflight.done():
            inflight.set_result(result)
        return result

    # -- Cache management ----------------------------------------------------
    # (single-event-loop usage; individual dict ops are atomic under the GIL)

    def invalidate(self, **kwargs: Any) -> bool:
        """Remove a specific entry from the cache.  Returns *True* if found."""
        return self._cache.pop(self._make_key(kwargs), None) is not None

    def clear(self) -> int:
        """Drop all cached entries.  Returns the number evicted."""
        count = len(self._cache)
        self._cache.clear()
        return count

    @property
    def cache_size(self) -> int:
        """Number of entries currently in the cache (including expired)."""
        return len(self._cache)

    # -- Internals -----------------------------------------------------------

    @staticmethod
    def _make_key(kwargs: dict[str, Any]) -> str:
        """Produce a deterministic hash for the given kwargs."""
        canonical = json.dumps(kwargs, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _put(self, key: str, value: Any, now: float) -> None:
        """Store *value* in the cache, evicting the oldest entry if full."""
        if len(self._cache) >= self._max_entries:
            # Evict oldest by insertion order (dict is ordered in Python 3.7+)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[key] = _CacheEntry(value, now + self._ttl)

    def __repr__(self) -> str:
        return f"CachedTool(tool={self._tool!r}, ttl={self._ttl}s)"
