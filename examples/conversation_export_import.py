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

"""Conversation export/import and LLM summarizer example.

Demonstrates:
- ``ConversationMemory.export_conversation()`` — serialise to JSON-safe dict.
- ``ConversationMemory.import_conversation()`` — restore from export.
- Cross-instance migration of conversation history.
- ``create_llm_summarizer()`` — LLM-based conversation compression.

Usage::

    uv run python examples/conversation_export_import.py

.. note:: This example does NOT require an OpenAI API key for the
   export/import demo.  The LLM summarizer section is shown but not
   executed without a key.
"""

from __future__ import annotations

import json


def main() -> None:
    from fireflyframework_agentic.memory.conversation import ConversationMemory

    # ── 1. Build a conversation ─────────────────────────────────────────
    print("=== Build a Conversation ===\n")

    mem = ConversationMemory(max_tokens=10_000)
    cid = mem.new_conversation()
    mem.add_turn(cid, "Hi, I'm Alice.", "Hello Alice! How can I help?", [])
    mem.add_turn(cid, "What's the capital of France?", "The capital of France is Paris.", [])
    mem.add_turn(
        cid,
        "Tell me about its population.",
        "Paris has approximately 2.1 million residents in the city proper.",
        [],
        metadata={"topic": "geography", "confidence": 0.95},
    )

    turns = mem.get_turns(cid)
    print(f"  Conversation {cid[:8]}... has {len(turns)} turns")
    print(f"  Total tokens: {mem.get_total_tokens(cid)}")

    # ── 2. Export ───────────────────────────────────────────────────────
    print("\n=== Export Conversation ===\n")

    data = mem.export_conversation(cid)
    json_str = json.dumps(data, indent=2)
    print(f"  Exported as JSON ({len(json_str)} chars):")
    print(f"  Keys: {list(data.keys())}")
    print(f"  Turns: {len(data['turns'])}")
    print(f"  First turn: {data['turns'][0]['user_prompt']}")

    # ── 3. Import into a fresh instance ─────────────────────────────────
    print("\n=== Import into Fresh ConversationMemory ===\n")

    mem2 = ConversationMemory()
    imported_id = mem2.import_conversation(data)
    imported_turns = mem2.get_turns(imported_id)
    print(f"  Imported conversation: {imported_id[:8]}...")
    print(f"  Turns restored: {len(imported_turns)}")
    print(f"  Turn 1 prompt : {imported_turns[0].user_prompt}")
    print(f"  Turn 3 metadata: {imported_turns[2].metadata}")

    # ── 4. Import with override ID ──────────────────────────────────────
    print("\n=== Import with Custom ID ===\n")

    custom_id = mem2.import_conversation(data, conversation_id="migrated-conv-001")
    print(f"  Custom ID: {custom_id}")
    print(f"  Turns: {len(mem2.get_turns(custom_id))}")

    # ── 5. Export empty conversation ────────────────────────────────────
    print("\n=== Export Empty Conversation ===\n")

    empty = mem.export_conversation("nonexistent")
    print(f"  Keys: {list(empty.keys())}")
    print(f"  Turns: {empty['turns']}")
    print(f"  Total tokens: {empty['total_tokens']}")

    # ── 6. Import with summary ──────────────────────────────────────────
    print("\n=== Import with Summary ===\n")

    data_with_summary = {
        "conversation_id": "summarised-conv",
        "turns": [{"user_prompt": "Continue our chat", "assistant_response": "Sure!"}],
        "summary": "Previously discussed Python web frameworks and deployment.",
    }
    sid = mem2.import_conversation(data_with_summary)
    print(f"  Imported: {sid}")
    print(f"  Summary: {mem2.get_summary(sid)}")

    # ── 7. LLM summarizer factory ───────────────────────────────────────
    print("\n=== LLM Summarizer (factory demo) ===\n")

    from fireflyframework_agentic.memory.summarization import create_llm_summarizer

    summarizer = create_llm_summarizer()
    print(f"  create_llm_summarizer() → {type(summarizer).__name__} (callable={callable(summarizer)})")

    summarizer_mini = create_llm_summarizer(model="openai:gpt-4o-mini")
    print(f"  create_llm_summarizer(model='openai:gpt-4o-mini') → callable={callable(summarizer_mini)}")

    print("\n  To use the summarizer with ConversationMemory:")
    print("    mem = ConversationMemory(summarizer=create_llm_summarizer())")

    print("\nConversation export/import demo complete.")


if __name__ == "__main__":
    main()
