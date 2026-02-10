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

"""Server-Sent Events (SSE) streaming support for agent responses."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fireflyframework_genai.types import AgentLike


async def sse_stream(agent: AgentLike, prompt: Any, **kwargs: Any) -> AsyncIterator[str]:
    """Yield SSE-formatted events from an agent's streaming response.

    Each yielded string is a complete SSE event (``data: ...\\n\\n``).

    This uses buffered streaming mode (chunks/messages).
    """
    async with await cast("Any", agent).run_stream(prompt, **kwargs) as stream:
        async for chunk in stream.stream_text():
            yield f"data: {json.dumps({'text': chunk})}\n\n"
    yield "data: [DONE]\n\n"


async def sse_stream_incremental(
    agent: AgentLike,
    prompt: Any,
    debounce_ms: float = 0.0,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Yield SSE-formatted events with true token-by-token streaming.

    This provides minimal latency streaming by yielding individual tokens
    as they arrive from the model, without buffering into chunks.

    Args:
        agent: The agent to run.
        prompt: The prompt to send.
        debounce_ms: Optional debounce delay in milliseconds to batch
            rapid tokens. Default 0 = no debouncing.
        **kwargs: Additional arguments passed to run_stream().

    Yields:
        SSE-formatted token events with minimal latency.

    Example SSE event:
        data: {"token": "Hello"}\\n\\n
    """
    async with await cast("Any", agent).run_stream(prompt, streaming_mode="incremental", **kwargs) as stream:
        async for token in stream.stream_tokens(debounce_ms=debounce_ms):
            yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"
