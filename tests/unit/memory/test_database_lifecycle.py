"""Database clients must never leave the event loop that created them."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fireflyframework_agentic.config import FireflyAgenticConfig
from fireflyframework_agentic.exceptions import DatabaseConnectionError
from fireflyframework_agentic.memory import database_store, manager
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.memory.types import MemoryEntry


class _LoopBoundDatabase:
    """Replace only driver I/O while enforcing driver loop and serialization rules."""

    def __init__(self, *, fail_setup=False):
        self.loop = asyncio.get_running_loop()
        self.documents = {}
        self.closed = False
        self.fail_setup = fail_setup
        self.admin = self
        self.query = {}
        self.tz_aware = False

    def check(self):
        assert asyncio.get_running_loop() is self.loop, "database client used on another event loop"
        assert not self.closed

    def acquire(self):
        self.check()
        return self

    async def __aenter__(self):
        self.check()
        return self

    async def __aexit__(self, *args):
        self.check()

    async def execute(self, query, *args):
        self.check()
        await asyncio.sleep(0)
        if "CREATE" in query and self.fail_setup:
            raise RuntimeError("schema setup failed")
        if "INSERT INTO" in query:
            assert isinstance(args[5], str), "asyncpg JSONB parameters require JSON text"
            doc = json.loads(args[4])
            assert json.loads(args[5]) == doc["metadata"]
            self.documents[args[0]] = {"namespace": args[1], "content": args[4], "key": args[3]}
        if "DELETE FROM" in query:
            if "namespace" in query:
                ids = [
                    key
                    for key, doc in self.documents.items()
                    if doc["namespace"] == args[0] and (len(args) < 2 or key == args[1])
                ]
            else:
                ids = [
                    key
                    for key, doc in self.documents.items()
                    if MemoryEntry.model_validate_json(doc["content"]).is_expired
                ]
            for key in ids:
                del self.documents[key]
            return f"DELETE {len(ids)}"
        return "OK"

    async def fetch(self, query, namespace, *args):
        self.check()
        return [
            doc
            for doc in self.documents.values()
            if doc["namespace"] == namespace and not MemoryEntry.model_validate_json(doc["content"]).is_expired
        ]

    async def fetchrow(self, query, namespace, key, *args):
        return next((doc for doc in await self.fetch(query, namespace) if doc["key"] == key), None)

    async def close_pool(self):
        self.check()
        self.closed = True

    def __getitem__(self, name):
        self.check()
        return self

    async def command(self, name):
        self.check()
        await asyncio.sleep(0)
        if self.fail_setup:
            raise RuntimeError("ping failed")
        return {"ok": 1}

    async def create_index(self, *args, **kwargs):
        self.check()

    async def update_one(self, query, update, *, upsert):
        self.check()
        doc = update["$set"]
        assert isinstance(doc["created_at"], datetime), "MongoDB timestamps must be BSON dates"
        assert doc["expires_at"] is None or isinstance(doc["expires_at"], datetime)
        self.documents[doc["entry_id"]] = doc

    def _matching(self, query):
        matches = [
            doc
            for doc in self.documents.values()
            if all(doc.get(k) == v for k, v in query.items() if k in {"namespace", "entry_id", "key"})
        ]
        if "$or" in query:
            matches = [doc for doc in matches if doc["expires_at"] is None or doc["expires_at"] > datetime.now(UTC)]
        if "expires_at" in query:
            matches = [
                doc for doc in matches if doc["expires_at"] is not None and doc["expires_at"] <= datetime.now(UTC)
            ]
        return matches

    def find(self, query):
        self.check()
        self.query = query
        return self

    def sort(self, *args):
        self.check()
        return self

    async def to_list(self, length):
        self.check()
        return [self._decoded(doc) for doc in self._matching(self.query)]

    def _decoded(self, doc):
        # BSON stores UTC instants, and PyMongo decodes them as naive UTC unless
        # tz_aware=True was requested on the actual client constructor.
        return {
            key: value.replace(tzinfo=None) if isinstance(value, datetime) and not self.tz_aware else value
            for key, value in doc.items()
        }

    async def find_one(self, query, **kwargs):
        self.check()
        doc = next(iter(self._matching(query)), None)
        return self._decoded(doc) if doc is not None else None

    async def delete_one(self, query):
        self.check()
        for doc in self._matching(query)[:1]:
            del self.documents[doc["entry_id"]]

    async def delete_many(self, query):
        self.check()
        docs = self._matching(query)
        for doc in docs:
            del self.documents[doc["entry_id"]]
        return SimpleNamespace(deleted_count=len(docs))

    def close_client(self):
        self.check()
        self.closed = True


@pytest.fixture(params=["postgres", "mongodb"])
def database(request, monkeypatch):
    clients = []
    fail_setup = [False]

    async def create_pool(*args, **kwargs):
        client = _LoopBoundDatabase(fail_setup=fail_setup[0])
        client.close = client.close_pool
        clients.append(client)
        await asyncio.sleep(0)
        return client

    def create_client(*args, **kwargs):
        client = _LoopBoundDatabase(fail_setup=fail_setup[0])
        client.tz_aware = kwargs.get("tz_aware", False)
        client.close = client.close_client
        clients.append(client)
        return client

    monkeypatch.setattr(database_store, "asyncpg", SimpleNamespace(create_pool=create_pool))
    monkeypatch.setattr(database_store, "AsyncIOMotorClient", create_client)
    backend = request.param
    cls = database_store.PostgreSQLStore if backend == "postgres" else database_store.MongoDBStore
    return SimpleNamespace(
        backend=backend, create=lambda: cls(url=f"{backend}://offline-test"), clients=clients, fail_setup=fail_setup
    )


async def test_initialized_store_supports_sync_and_async_calls_on_one_driver_loop(database):
    store = database.create()
    await store.initialize()
    entry = MemoryEntry(key="answer", content=42, metadata={"source": "test"})
    try:
        store.save("tenant", entry)
        assert (await store.async_load_by_key("tenant", "answer")).content == 42
        assert store.load("tenant")[0].entry_id == entry.entry_id
        await store.async_delete("tenant", entry.entry_id)
        assert store.load_by_key("tenant", "answer") is None
        await store.async_save("tenant", entry)
        store.clear("tenant")
        assert await store.async_load("tenant") == []
    finally:
        await store.close()
    assert database.clients[0].closed
    await store.close()


def test_store_survives_multiple_top_level_event_loops(database):
    store = database.create()
    asyncio.run(store.initialize(), loop_factory=asyncio.new_event_loop)
    try:
        store.save("tenant", MemoryEntry(key="value", content=7))
        assert asyncio.run(store.async_load("tenant"), loop_factory=asyncio.new_event_loop)[0].content == 7
        assert store.load_by_key("tenant", "value").content == 7
    finally:
        asyncio.run(store.close(), loop_factory=asyncio.new_event_loop)


async def test_native_json_and_expiry_are_encoded_for_the_database(database):
    store = database.create()
    live = MemoryEntry(
        key="live",
        metadata={"when": datetime(2026, 1, 1, tzinfo=UTC)},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    expired = MemoryEntry(key="expired", expires_at=datetime.now(UTC) - timedelta(hours=1))
    try:
        await store.async_save("tenant", live)
        await store.async_save("tenant", expired)
        loaded = await store.async_load("tenant")
        assert [entry.key for entry in loaded] == ["live"]
        assert loaded[0].is_expired is False
        assert await store.cleanup_expired() == 1
    finally:
        await store.close()


async def test_concurrent_initialization_creates_only_one_connection_pool(database):
    store = database.create()
    try:
        await asyncio.gather(store.initialize(), store.initialize(), store.initialize())
        assert len(database.clients) == 1
    finally:
        await store.close()


async def test_failed_initialization_closes_partial_resources_and_can_retry(database):
    database.fail_setup[0] = True
    store = database.create()
    with pytest.raises(DatabaseConnectionError):
        await store.initialize()
    assert database.clients[0].closed
    database.fail_setup[0] = False
    try:
        await store.initialize()
        await store.async_save("tenant", MemoryEntry(key="recovered", content=True))
    finally:
        await store.close()
    assert all(client.closed for client in database.clients)


async def test_manager_from_config_has_a_live_backend_inside_async_app(database, monkeypatch):
    cfg = FireflyAgenticConfig(
        memory_backend=database.backend,
        memory_postgres_url="postgresql://offline-test",
        memory_mongodb_url="mongodb://offline-test",
    )
    monkeypatch.setattr(manager, "get_config", lambda: cfg)
    memory = MemoryManager.from_config()
    try:
        memory.set_fact("answer", 42)
        assert memory.get_fact("answer") == 42
    finally:
        await memory.aclose()
    assert database.clients[0].closed


def test_manager_sync_factory_and_close_do_not_depend_on_a_caller_event_loop(database, monkeypatch):
    monkeypatch.setattr(
        manager,
        "get_config",
        lambda: FireflyAgenticConfig(
            memory_backend=database.backend,
            memory_postgres_url="postgresql://offline-test",
            memory_mongodb_url="mongodb://offline-test",
        ),
    )
    memory = MemoryManager.from_config()
    try:
        memory.set_fact("persisted", "yes")
        assert memory.get_fact("persisted") == "yes"
    finally:
        memory.close()
    assert database.clients[0].closed
