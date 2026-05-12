# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Provider-agnostic primitives for per-corpus capability tokens.

This module purposely contains **no provider-specific imports**. The
framework defines the contract — a token store the middleware can call,
plus an in-memory TTL cache — and concrete implementations live in
provider-specific extras (e.g. ``examples/corpus_search/azure_security.py``
ships ``KeyVaultTokenStore`` for Azure Key Vault).

Plaintext tokens are never retained beyond the request scope. The cache
stores ``sha256(token + corpus_id)`` digests only, keyed by ``corpus_id``,
so a hit for corpus A cannot validate a request for corpus B even with
the same bearer.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_CORPUS_ID_RE = re.compile(r"^[a-z0-9-]{1,63}$")


def _monotonic() -> float:
    """Indirection so tests can freeze time without monkey-patching ``time``."""
    return time.monotonic()


def corpus_token_digest(token: str, corpus_id: str) -> str:
    """Bind ``token`` to ``corpus_id`` for cache lookups.

    Including ``corpus_id`` in the hashed payload prevents a cached digest
    for corpus A from validating a request for corpus B.
    """
    return hashlib.sha256(f"{token}|{corpus_id}".encode()).hexdigest()


@dataclass(slots=True)
class _Entry:
    digest: str
    expires_at: float


class CorpusTokenCache:
    """In-memory TTL cache of corpus_id → trusted digest."""

    def __init__(self, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = float(ttl_seconds)
        self._entries: dict[str, _Entry] = {}

    def remember(self, corpus_id: str, digest: str) -> None:
        self._entries[corpus_id] = _Entry(digest=digest, expires_at=_monotonic() + self._ttl)

    def is_trusted(self, corpus_id: str, digest: str) -> bool:
        entry = self._entries.get(corpus_id)
        if entry is None:
            return False
        if _monotonic() >= entry.expires_at:
            self._entries.pop(corpus_id, None)
            return False
        return hmac.compare_digest(entry.digest, digest)

    def forget(self, corpus_id: str) -> None:
        self._entries.pop(corpus_id, None)


def validate_corpus_id(corpus_id: str) -> None:
    """Raise ValueError if ``corpus_id`` does not match the framework's contract.

    The contract — ``[a-z0-9-]{1,63}`` — is enforced everywhere a
    ``corpus_id`` is accepted from a caller. Centralised here so
    concrete stores can call it without re-importing the regex.
    """
    if not _CORPUS_ID_RE.match(corpus_id):
        raise ValueError(f"invalid corpus_id: {corpus_id!r}")


@runtime_checkable
class CorpusTokenStore(Protocol):
    """Contract every concrete token store must satisfy.

    Implementations resolve ``corpus_id`` to the current bearer for that
    corpus, fetched from whatever back-end the deployment uses (Azure
    Key Vault, HashiCorp Vault, a local JSON file in tests, …). The
    middleware depends on this Protocol only, so adding a new provider
    requires no framework changes.

    Return ``None`` for not-found / disabled secrets so the caller can
    map those to ``403 Forbidden`` without revealing whether the secret
    exists. Other back-end errors should propagate so the caller can
    fail closed (``503``).
    """

    async def get_corpus_token(self, corpus_id: str) -> str | None:
        # ``raise NotImplementedError`` keeps this method body unambiguous
        # for static analysers that flag bare ``...`` as "statement has
        # no effect", while staying inert at runtime — Protocol methods
        # are never called via the Protocol class itself.
        raise NotImplementedError
