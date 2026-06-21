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

"""Streaming a *structured* (non-text) output must not crash.

pydantic-ai forbids ``stream_text()`` for a non-text run; both the workflow
``StreamHandle.text()`` and the agent incremental ``stream_tokens()`` used to
call it unconditionally and raise an opaque ``UserError``. Now ``text()`` falls
back to stringified ``stream_output()`` snapshots, and ``stream_tokens()`` raises
a clear, actionable ``AgentError``.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.exceptions import AgentError
from fireflyframework_agentic.workflows import FireflyAgentRunner, stream, workflow


class _Out(BaseModel):
    answer: str


def _structured_model() -> TestModel:
    return TestModel(custom_output_args={"answer": "hi"})


@pytest.mark.asyncio
async def test_workflow_stream_structured_output_does_not_crash():
    @workflow(register=False)
    async def wf(args, ctx):
        chunks: list[str] = []
        async with stream("go", model=_structured_model(), output_type=_Out) as s:
            async for chunk in s.text():
                chunks.append(chunk)
        return chunks, s.output

    chunks, out = await wf.run(None, runner=FireflyAgentRunner())
    assert isinstance(out, _Out)
    assert out.answer == "hi"
    assert chunks  # got stringified snapshot(s) instead of crashing
    assert "hi" in "".join(chunks)


@pytest.mark.asyncio
async def test_incremental_stream_tokens_structured_raises_clear_error():
    ag = FireflyAgent("e2e-struct-stream", model=_structured_model(), output_type=_Out, auto_register=False)
    with pytest.raises(AgentError, match="text output_type"):
        async with await ag.run_stream("go", streaming_mode="incremental") as s:
            async for _ in s.stream_tokens():
                pass
