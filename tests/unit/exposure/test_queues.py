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

"""Tests for queue exposure."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.exceptions import ExposureError
from fireflyframework_agentic.exposure.queues.base import QueueMessage
from fireflyframework_agentic.exposure.queues.router import QueueRouter


class TestQueueMessage:
    def test_message_creation(self):
        msg = QueueMessage(body="hello", routing_key="test.key")
        assert msg.body == "hello"
        assert msg.routing_key == "test.key"

    def test_message_defaults(self):
        msg = QueueMessage(body="hi")
        assert msg.headers == {}
        assert msg.routing_key == ""
        assert msg.reply_to == ""


class TestQueueRouter:
    def test_add_route(self):
        router = QueueRouter()
        router.add_route(r"test\..*", "test_agent")
        assert len(router._routes) == 1

    def test_resolve_matches_pattern(self):
        router = QueueRouter()
        router.add_route(r"summary\..*", "summariser")
        assert router._resolve("summary.en") == "summariser"

    def test_resolve_default_agent(self):
        router = QueueRouter(default_agent="fallback")
        assert router._resolve("unknown.key") == "fallback"

    def test_resolve_no_match_no_default_raises(self):
        router = QueueRouter()
        with pytest.raises(ExposureError):
            router._resolve("unknown.key")
