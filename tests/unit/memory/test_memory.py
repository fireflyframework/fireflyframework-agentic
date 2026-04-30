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

"""Tests for the memory subsystem."""

from fireflyframework_agentic.memory.conversation import ConversationMemory
from fireflyframework_agentic.memory.manager import MemoryManager
from fireflyframework_agentic.memory.store import FileStore, InMemoryStore, MemoryStore
from fireflyframework_agentic.memory.types import ConversationTurn, MemoryEntry, MemoryScope
from fireflyframework_agentic.memory.working import WorkingMemory

# -- MemoryEntry tests -----------------------------------------------------


class TestMemoryEntry:
    def test_default_values(self):
        entry = MemoryEntry(content="test")
        assert entry.scope == MemoryScope.WORKING
        assert entry.importance == 0.5
        assert entry.is_expired is False
        assert entry.entry_id  # auto-generated

    def test_scope_enum(self):
        assert MemoryScope.CONVERSATION == "conversation"
        assert MemoryScope.WORKING == "working"
        assert MemoryScope.LONG_TERM == "long_term"

    def test_conversation_turn(self):
        turn = ConversationTurn(
            turn_id=0,
            user_prompt="hello",
            assistant_response="hi",
            token_estimate=10,
        )
        assert turn.user_prompt == "hello"
        assert turn.assistant_response == "hi"
        assert turn.raw_messages == []


# -- InMemoryStore tests ---------------------------------------------------


class TestInMemoryStore:
    def test_save_and_load(self):
        store = InMemoryStore()
        entry = MemoryEntry(key="k1", content="v1")
        store.save("ns1", entry)
        loaded = store.load("ns1")
        assert len(loaded) == 1
        assert loaded[0].content == "v1"

    def test_load_by_key(self):
        store = InMemoryStore()
        entry = MemoryEntry(key="target", content="found")
        store.save("ns", entry)
        assert store.load_by_key("ns", "target").content == "found"
        assert store.load_by_key("ns", "missing") is None

    def test_delete(self):
        store = InMemoryStore()
        entry = MemoryEntry(key="k", content="v")
        store.save("ns", entry)
        store.delete("ns", entry.entry_id)
        assert store.load("ns") == []

    def test_clear(self):
        store = InMemoryStore()
        store.save("ns", MemoryEntry(content="a"))
        store.save("ns", MemoryEntry(content="b"))
        store.clear("ns")
        assert store.load("ns") == []

    def test_namespaces(self):
        store = InMemoryStore()
        store.save("ns1", MemoryEntry(content="a"))
        store.save("ns2", MemoryEntry(content="b"))
        assert set(store.namespaces) == {"ns1", "ns2"}

    def test_implements_protocol(self):
        assert isinstance(InMemoryStore(), MemoryStore)


# -- FileStore tests -------------------------------------------------------


class TestFileStore:
    def test_save_and_load(self, tmp_path):
        store = FileStore(base_dir=tmp_path / "mem")
        entry = MemoryEntry(key="k1", content="v1")
        store.save("test_ns", entry)
        loaded = store.load("test_ns")
        assert len(loaded) == 1
        assert loaded[0].content == "v1"

    def test_clear(self, tmp_path):
        store = FileStore(base_dir=tmp_path / "mem")
        store.save("ns", MemoryEntry(content="data"))
        store.clear("ns")
        assert store.load("ns") == []

    def test_load_by_key(self, tmp_path):
        store = FileStore(base_dir=tmp_path / "mem")
        store.save("ns", MemoryEntry(key="mykey", content="myval"))
        assert store.load_by_key("ns", "mykey").content == "myval"

    def test_delete(self, tmp_path):
        store = FileStore(base_dir=tmp_path / "mem")
        entry = MemoryEntry(content="data")
        store.save("ns", entry)
        store.delete("ns", entry.entry_id)
        assert store.load("ns") == []

    def test_implements_protocol(self, tmp_path):
        assert isinstance(FileStore(base_dir=tmp_path), MemoryStore)


# -- ConversationMemory tests ---------------------------------------------


class TestConversationMemory:
    def test_add_turn_and_get_history(self):
        mem = ConversationMemory(max_tokens=10000)
        cid = mem.new_conversation()

        # Simulate raw ModelMessage objects as plain dicts for testing
        fake_msgs = [{"kind": "request", "content": "hello"}, {"kind": "response", "content": "hi"}]
        mem.add_turn(cid, "hello", "hi", fake_msgs)

        history = mem.get_message_history(cid)
        assert len(history) == 2
        assert history[0]["content"] == "hello"

    def test_token_budget_eviction(self):
        mem = ConversationMemory(max_tokens=50)
        cid = mem.new_conversation()

        # Each turn ~20 tokens (10 words * 1.33)
        for i in range(5):
            text = " ".join(f"word{j}" for j in range(10))
            mem.add_turn(cid, text, text, [f"msg_{i}"])

        history = mem.get_message_history(cid)
        # Should have fewer than 5 turns' worth of messages
        assert len(history) < 5

    def test_get_turns(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "q1", "a1", [])
        mem.add_turn(cid, "q2", "a2", [])
        turns = mem.get_turns(cid)
        assert len(turns) == 2
        assert turns[0].turn_id == 0
        assert turns[1].turn_id == 1

    def test_clear(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "q", "a", [])
        mem.clear(cid)
        assert mem.get_turns(cid) == []

    def test_conversation_ids(self):
        mem = ConversationMemory()
        c1 = mem.new_conversation()
        c2 = mem.new_conversation()
        assert set(mem.conversation_ids) == {c1, c2}

    def test_empty_conversation(self):
        mem = ConversationMemory()
        assert mem.get_message_history("nonexistent") == []

    def test_total_tokens(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "hello world", "hi there", [])
        assert mem.get_total_tokens(cid) > 0


# -- WorkingMemory tests ---------------------------------------------------


class TestWorkingMemory:
    def test_set_and_get(self):
        wm = WorkingMemory()
        wm.set("key1", "value1")
        assert wm.get("key1") == "value1"

    def test_get_default(self):
        wm = WorkingMemory()
        assert wm.get("missing", "default") == "default"

    def test_has(self):
        wm = WorkingMemory()
        wm.set("exists", True)
        assert wm.has("exists") is True
        assert wm.has("nope") is False

    def test_delete(self):
        wm = WorkingMemory()
        wm.set("k", "v")
        wm.delete("k")
        assert wm.has("k") is False

    def test_keys_and_items(self):
        wm = WorkingMemory()
        wm.set("a", 1)
        wm.set("b", 2)
        assert set(wm.keys()) == {"a", "b"}
        assert set(wm.items()) == {("a", 1), ("b", 2)}

    def test_to_dict(self):
        wm = WorkingMemory()
        wm.set("x", 10)
        wm.set("y", 20)
        assert wm.to_dict() == {"x": 10, "y": 20}

    def test_to_context_string(self):
        wm = WorkingMemory()
        wm.set("doc_type", "invoice")
        ctx = wm.to_context_string()
        assert "Working Memory:" in ctx
        assert "doc_type: invoice" in ctx

    def test_empty_context_string(self):
        wm = WorkingMemory()
        assert wm.to_context_string() == ""

    def test_clear(self):
        wm = WorkingMemory()
        wm.set("a", 1)
        wm.clear()
        assert wm.keys() == []

    def test_replace_existing_key(self):
        wm = WorkingMemory()
        wm.set("k", "old")
        wm.set("k", "new")
        assert wm.get("k") == "new"

    def test_scoped_isolation(self):
        store = InMemoryStore()
        wm1 = WorkingMemory(store=store, scope_id="agent_a")
        wm2 = WorkingMemory(store=store, scope_id="agent_b")
        wm1.set("k", "from_a")
        wm2.set("k", "from_b")
        assert wm1.get("k") == "from_a"
        assert wm2.get("k") == "from_b"


# -- MemoryManager tests ---------------------------------------------------


class TestMemoryManager:
    def test_conversation_shortcuts(self):
        mgr = MemoryManager()
        cid = mgr.new_conversation()
        mgr.add_turn(cid, "q", "a", ["msg1"])
        history = mgr.get_message_history(cid)
        assert len(history) == 1

    def test_working_shortcuts(self):
        mgr = MemoryManager()
        mgr.set_fact("key", "val")
        assert mgr.get_fact("key") == "val"

    def test_working_context(self):
        mgr = MemoryManager()
        mgr.set_fact("x", 42)
        ctx = mgr.get_working_context()
        assert "x: 42" in ctx

    def test_clear_all(self):
        mgr = MemoryManager()
        cid = mgr.new_conversation()
        mgr.add_turn(cid, "q", "a", [])
        mgr.set_fact("k", "v")
        mgr.clear_all()
        assert mgr.get_message_history(cid) == []
        assert mgr.get_fact("k") is None

    def test_fork(self):
        mgr = MemoryManager()
        mgr.set_fact("parent_key", "parent_val")
        child = mgr.fork(working_scope_id="child")
        child.set_fact("child_key", "child_val")
        # Parent doesn't see child's working memory
        assert mgr.get_fact("child_key") is None
        # Child doesn't see parent's working memory (different scope)
        assert child.get_fact("parent_key") is None
        # But they share conversation memory
        cid = mgr.new_conversation()
        mgr.add_turn(cid, "q", "a", ["msg"])
        assert len(child.get_message_history(cid)) == 1

    def test_clear_conversation(self):
        mgr = MemoryManager()
        cid = mgr.new_conversation()
        mgr.add_turn(cid, "q", "a", [])
        mgr.clear_conversation(cid)
        assert mgr.get_message_history(cid) == []

    def test_clear_working(self):
        mgr = MemoryManager()
        mgr.set_fact("k", "v")
        mgr.clear_working()
        assert mgr.get_fact("k") is None


# -- Conversation export / import tests ------------------------------------

import json  # noqa: E402


class TestConversationExportImport:
    def test_export_empty_conversation(self):
        mem = ConversationMemory()
        data = mem.export_conversation("nonexistent")
        assert data["conversation_id"] == "nonexistent"
        assert data["turns"] == []
        assert data["total_tokens"] == 0

    def test_export_with_turns(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "hello", "hi", [])
        data = mem.export_conversation(cid)
        assert len(data["turns"]) == 1
        assert data["turns"][0]["user_prompt"] == "hello"

    def test_export_round_trip(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "q1", "a1", [])
        mem.add_turn(cid, "q2", "a2", [])
        data = mem.export_conversation(cid)

        mem2 = ConversationMemory()
        imported_id = mem2.import_conversation(data)

        turns = mem2.get_turns(imported_id)
        assert len(turns) == 2
        assert turns[0].user_prompt == "q1"
        assert turns[1].assistant_response == "a2"

    def test_import_with_override_id(self):
        mem = ConversationMemory()
        data = {"turns": [{"user_prompt": "hi", "assistant_response": "hey"}]}
        cid = mem.import_conversation(data, conversation_id="custom-id")
        assert cid == "custom-id"
        turns = mem.get_turns(cid)
        assert len(turns) == 1

    def test_import_with_summary(self):
        mem = ConversationMemory()
        data = {
            "conversation_id": "sum-test",
            "turns": [],
            "summary": "Previously discussed weather.",
        }
        mem.import_conversation(data)
        assert mem._summaries.get("sum-test") == "Previously discussed weather."

    def test_export_is_json_serializable(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "test", "response", [])
        data = mem.export_conversation(cid)
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

    def test_import_reestimates_zero_tokens(self):
        mem = ConversationMemory()
        data = {
            "turns": [
                {
                    "user_prompt": "hello world",
                    "assistant_response": "hi there",
                    "token_estimate": 0,
                }
            ],
        }
        cid = mem.import_conversation(data, conversation_id="re-est")
        turns = mem.get_turns(cid)
        assert len(turns) == 1
        assert turns[0].token_estimate > 0

    def test_import_empty_data(self):
        mem = ConversationMemory()
        cid = mem.import_conversation({})
        assert isinstance(cid, str)
        assert mem.get_turns(cid) == []

    def test_export_import_preserves_metadata(self):
        mem = ConversationMemory()
        cid = mem.new_conversation()
        mem.add_turn(cid, "q", "a", [], metadata={"source": "test", "priority": 1})
        data = mem.export_conversation(cid)
        mem2 = ConversationMemory()
        imported = mem2.import_conversation(data)
        turns = mem2.get_turns(imported)
        assert turns[0].metadata == {"source": "test", "priority": 1}
