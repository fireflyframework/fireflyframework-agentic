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

"""SP-2: lossless ModelMessage persistence across conversation export/import."""

from __future__ import annotations

import json

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from fireflyframework_agentic.memory.conversation import ConversationMemory
from fireflyframework_agentic.model_utils import deserialize_model_messages, serialize_model_messages


def _messages() -> list:
    return [
        ModelRequest(parts=[UserPromptPart(content="what is 2+2?")]),
        ModelResponse(parts=[TextPart(content="4")]),
    ]


class TestModelMessageCodec:
    def test_round_trip_preserves_types_and_content(self):
        dumped = serialize_model_messages(_messages())
        json.dumps(dumped)  # must be JSON-serialisable
        restored = deserialize_model_messages(dumped)
        assert [type(m).__name__ for m in restored] == ["ModelRequest", "ModelResponse"]
        assert restored[0].parts[0].content == "what is 2+2?"
        assert restored[1].parts[0].content == "4"

    def test_empty_inputs(self):
        assert serialize_model_messages([]) == []
        assert deserialize_model_messages([]) == []
        assert deserialize_model_messages(None) == []


class TestConversationExportImport:
    def test_export_is_json_serialisable_and_preserves_raw_messages(self):
        mem = ConversationMemory()
        mem.add_turn("c1", "what is 2+2?", "4", _messages())

        exported = mem.export_conversation("c1")
        json.dumps(exported)  # regression: raw_messages used to be dropped/non-portable
        assert exported["turns"][0]["raw_messages"]  # present and non-empty

        mem2 = ConversationMemory()
        cid = mem2.import_conversation(exported)

        turn = mem2.get_turns(cid)[0]
        assert [type(m).__name__ for m in turn.raw_messages] == ["ModelRequest", "ModelResponse"]
        assert turn.raw_messages[0].parts[0].content == "what is 2+2?"

        # get_message_history flattens the restored raw messages
        history = mem2.get_message_history(cid)
        assert len(history) == 2
        assert history[1].parts[0].content == "4"

    def test_import_without_raw_messages_is_backward_compatible(self):
        # Old exports (pre-SP-2) have no "raw_messages" key — import must not break.
        legacy = {
            "conversation_id": "legacy",
            "turns": [{"turn_id": 0, "user_prompt": "hi", "assistant_response": "hello", "token_estimate": 3}],
            "summary": None,
        }
        mem = ConversationMemory()
        cid = mem.import_conversation(legacy)
        assert mem.get_turns(cid)[0].raw_messages == []
