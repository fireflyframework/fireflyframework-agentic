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

"""Agent result caching: in-memory cache keyed by model + prompt hash.

Usage::

    from fireflyframework_agentic.agents.cache import ResultCache

    cache = ResultCache(ttl_seconds=300, max_size=100)
    cached = cache.get("openai:gpt-4o", "summarise this text")
    if cached is None:
        result = await agent.run("summarise this text")
        cache.put("openai:gpt-4o", "summarise this text", result)
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)


class ResultCache:
    """In-memory LRU cache for agent run results.

    Keys are derived from a hash of the model name and prompt text.

    Parameters:
        ttl_seconds: Time-to-live for cached entries (0 = no expiry).
        max_size: Maximum number of entries (0 = unlimited).
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        max_size: int = 256,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(model: str, prompt: str) -> str:
        raw = f"{model}::{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, model: str, prompt: str) -> Any | None:
        """Return the cached result, or *None* on miss."""
        key = self._make_key(model, prompt)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if self._ttl > 0 and (time.monotonic() - ts) > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def put(self, model: str, prompt: str, result: Any) -> None:
        """Store a result in the cache."""
        key = self._make_key(model, prompt)
        with self._lock:
            self._cache[key] = (time.monotonic(), result)
            self._cache.move_to_end(key)
            if self._max_size > 0 and len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, model: str, prompt: str) -> bool:
        """Remove a specific entry.  Returns *True* if it existed."""
        key = self._make_key(model, prompt)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        """Return hit/miss statistics."""
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._cache),
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
