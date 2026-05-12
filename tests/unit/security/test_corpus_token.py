# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusTokenCache and KeyVaultTokenStore."""

from __future__ import annotations

import hashlib

import pytest


def _digest(token: str, corpus_id: str) -> str:
    return hashlib.sha256(f"{token}|{corpus_id}".encode()).hexdigest()


# ---------- CorpusTokenCache -----------------------------------------------


def test_cache_stores_and_returns_true_within_ttl() -> None:
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is True


def test_cache_rejects_wrong_digest() -> None:
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    assert cache.is_trusted("corpus-a", _digest("other", "corpus-a")) is False


def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from fireflyframework_agentic.security import corpus_token as kv_mod
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    fake_now = [1000.0]
    monkeypatch.setattr(kv_mod, "_monotonic", lambda: fake_now[0])

    cache = CorpusTokenCache(ttl_seconds=10)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))

    fake_now[0] = 1009.9
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is True

    fake_now[0] = 1010.1
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is False


def test_cache_is_corpus_scoped() -> None:
    """A hit for corpus-a must not validate corpus-b, even with the same token."""
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    assert cache.is_trusted("corpus-b", _digest("tok", "corpus-b")) is False


def test_cache_rejects_non_positive_ttl() -> None:
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    with pytest.raises(ValueError):
        CorpusTokenCache(ttl_seconds=0)


def test_cache_forget_clears_entry() -> None:
    from fireflyframework_agentic.security.corpus_token import CorpusTokenCache

    cache = CorpusTokenCache(ttl_seconds=60)
    cache.remember("corpus-a", _digest("tok", "corpus-a"))
    cache.forget("corpus-a")
    assert cache.is_trusted("corpus-a", _digest("tok", "corpus-a")) is False


# ---------- KeyVaultTokenStore ---------------------------------------------


class _FakeSecret:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeSecretClient:
    """Minimal async stub matching the subset of SecretClient we use."""

    def __init__(
        self,
        *,
        secrets: dict[str, str] | None = None,
        raise_for: dict[str, BaseException] | None = None,
    ) -> None:
        self._secrets = secrets or {}
        self._raise_for = raise_for or {}
        self.get_calls: list[str] = []

    async def get_secret(self, name: str) -> _FakeSecret:
        self.get_calls.append(name)
        if name in self._raise_for:
            raise self._raise_for[name]
        if name not in self._secrets:
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError(message=f"secret {name} not found")
        return _FakeSecret(self._secrets[name])

    async def close(self) -> None:  # pragma: no cover — cleanup only
        return None


@pytest.mark.asyncio
async def test_store_returns_secret_value() -> None:
    from examples.corpus_search.azure_security import KeyVaultTokenStore

    client = _FakeSecretClient(secrets={"firefly-mcp-corpus-token-demo": "abc"})
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    assert await store.get_corpus_token("demo") == "abc"
    assert client.get_calls == ["firefly-mcp-corpus-token-demo"]


@pytest.mark.asyncio
async def test_store_returns_none_when_not_found() -> None:
    from examples.corpus_search.azure_security import KeyVaultTokenStore

    client = _FakeSecretClient(secrets={})
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    assert await store.get_corpus_token("missing") is None


@pytest.mark.asyncio
async def test_store_propagates_service_errors() -> None:
    from azure.core.exceptions import ServiceRequestError

    from examples.corpus_search.azure_security import KeyVaultTokenStore

    err = ServiceRequestError(message="boom")
    client = _FakeSecretClient(raise_for={"firefly-mcp-corpus-token-x": err})
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    with pytest.raises(ServiceRequestError):
        await store.get_corpus_token("x")


@pytest.mark.asyncio
async def test_store_validates_corpus_id() -> None:
    """corpus_id must match the framework's [a-z0-9-]{1,63} contract."""
    from examples.corpus_search.azure_security import KeyVaultTokenStore

    client = _FakeSecretClient()
    store = KeyVaultTokenStore(client=client, prefix="firefly-mcp-corpus-token-")

    with pytest.raises(ValueError, match="corpus_id"):
        await store.get_corpus_token("Bad ID!")
