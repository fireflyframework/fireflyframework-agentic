# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Azure Key Vault token store + in-memory TTL cache for per-corpus
capability tokens used by the MCP HTTP server.

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
from typing import Any

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


class KeyVaultTokenStore:
    """Async fetcher for per-corpus tokens from Azure Key Vault.

    Returns ``None`` for not-found / disabled secrets so the caller can map
    those to ``403 Forbidden`` without revealing whether the secret exists.
    Other Azure errors propagate so the caller can fail closed (``503``).

    ``client`` is typed as ``Any`` rather than a Protocol because the real
    ``azure.keyvault.secrets.aio.SecretClient`` has a richer ``get_secret``
    signature (``version``, ``**kwargs``) than the subset we use, and
    structural matching against a slimmer Protocol upsets static checkers
    without buying real safety — the unit tests duck-type a stub that
    matches the same shape used here.
    """

    def __init__(self, *, client: Any, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    async def get_corpus_token(self, corpus_id: str) -> str | None:
        if not _CORPUS_ID_RE.match(corpus_id):
            raise ValueError(f"invalid corpus_id: {corpus_id!r}")
        from azure.core.exceptions import ResourceNotFoundError

        name = f"{self._prefix}{corpus_id}"
        try:
            secret = await self._client.get_secret(name)
        except ResourceNotFoundError:
            return None
        return getattr(secret, "value", None)

    async def aclose(self) -> None:
        await self._client.close()


def build_default_store(
    *,
    vault_url: str,
    prefix: str = "firefly-mcp-corpus-token-",
) -> KeyVaultTokenStore:
    """Construct a store wired to the real Azure SDK + DefaultAzureCredential.

    Uses managed identity in Azure Container Apps; falls back to ``az login``
    locally. The credential needs **Key Vault Secrets User** (``get``) — no
    ``list`` / ``set`` / ``delete``.
    """
    from azure.identity.aio import DefaultAzureCredential
    from azure.keyvault.secrets.aio import SecretClient

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    return KeyVaultTokenStore(client=client, prefix=prefix)
