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

"""Actual optional Ragas adapter, with deterministic model/embedding boundaries."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from typing import Any

import pytest

from fireflyframework_agentic.embeddings.base import BaseEmbedder
from fireflyframework_agentic.evaluation import judge

pytestmark = pytest.mark.skipif(importlib.util.find_spec("ragas") is None, reason="requires the evaluation extra")

_ITEM = {
    "question": "What is the capital of France?",
    "answer": "Paris is the capital of France.",
    "reference": "Paris is the capital of France.",
    "contexts": ["Paris is the capital of France."],
}
_STATEMENTS = {"sentences": [{"sentence_index": 0, "simpler_statements": ["Paris is the capital of France."]}]}


@pytest.fixture
def isolate_ragas_analytics(monkeypatch, tmp_path):
    # Ragas 0.2 builds analytics identities even when tracking is disabled.
    # Keep those files out of the caller's profile and disable network tracking.
    analytics = pytest.importorskip("ragas._analytics")
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")
    monkeypatch.setattr(analytics, "user_data_dir", lambda **kwargs: str(tmp_path / "ragas"))
    analytics.get_userid.cache_clear()
    analytics.do_not_track.cache_clear()
    try:
        yield
    finally:
        analytics.get_userid.cache_clear()
        analytics.do_not_track.cache_clear()


class _DeterministicEmbedder(BaseEmbedder):
    def __init__(self) -> None:
        super().__init__("offline-embedding", dimensions=2)
        self.texts: list[str] = []

    async def _embed_batch(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.texts.extend(texts)
        return [[1.0, 0.0] for _ in texts]


def test_optional_ragas_import_preserves_running_asyncio() -> None:
    # An import regression must fail without leaving the rest of pytest patched.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio
import importlib

async def main():
    original_task = asyncio.Task
    original_run = asyncio.run
    await asyncio.to_thread(importlib.import_module, 'ragas')
    assert asyncio.Task is original_task, 'Ragas import replaced asyncio.Task'
    assert asyncio.run is original_run, 'Ragas import replaced asyncio.run'
    async with asyncio.timeout(1):
        await asyncio.sleep(0)

asyncio.run(main())
print('clean shutdown')
""",
        ],
        env={**os.environ, "RAGAS_DO_NOT_TRACK": "true"},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "clean shutdown" in result.stdout


async def test_sample_and_embedding_adapter_preserve_values(
    monkeypatch: pytest.MonkeyPatch, isolate_ragas_analytics
) -> None:
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")
    embedder = _DeterministicEmbedder()
    context = judge.EvalContext(client=judge.JudgeClient("openai:gpt-6-luna"), embedder=embedder)
    sample = await asyncio.to_thread(judge._make_ragas_sample, _ITEM)
    assert sample.user_input == "What is the capital of France?"
    assert sample.response == "Paris is the capital of France."
    assert sample.retrieved_contexts == ["Paris is the capital of France."]
    wrapper = await asyncio.to_thread(judge._build_embeddings, context)
    assert await wrapper.embed_text("Paris") == [1.0, 0.0]
    assert embedder.texts == ["Paris"]


@pytest.mark.parametrize(
    "metric,responses,expected",
    [
        pytest.param(
            "answer_correctness",
            [
                _STATEMENTS,
                _STATEMENTS,
                {
                    "TP": [{"statement": "Paris is the capital of France.", "reason": "Matches the reference."}],
                    "FP": [],
                    "FN": [],
                },
            ],
            1.0,
            id="correctness",
        ),
        pytest.param(
            "ragas_faithfulness",
            [
                _STATEMENTS,
                {
                    "statements": [
                        {"statement": "Paris is the capital of France.", "reason": "In the context.", "verdict": 1}
                    ]
                },
            ],
            1.0,
            id="faithfulness",
        ),
        pytest.param(
            "context_recall",
            [
                {
                    "classifications": [
                        {"statement": "Paris is the capital of France.", "reason": "In the context.", "attributed": 1}
                    ]
                },
            ],
            1.0,
            id="recall",
        ),
        pytest.param(
            "context_precision", [{"reason": "The context answers the question.", "verdict": 1}], 1.0, id="precision"
        ),
        pytest.param(
            "context_precision",
            [{"reason": "The context does not answer the question.", "verdict": 0}],
            0.0,
            id="precision-zero",
        ),
    ],
)
async def test_real_ragas_metric_adapter(
    monkeypatch: pytest.MonkeyPatch,
    metric: str,
    responses: list[dict[str, Any]],
    expected: float,
    isolate_ragas_analytics,
) -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")
    llm = FakeListChatModel(responses=[json.dumps(response) for response in responses])
    monkeypatch.setattr(judge, "_make_ragas_llm", lambda context: llm)
    embedder = _DeterministicEmbedder()
    context = judge.EvalContext(client=judge.JudgeClient("openai:gpt-6-luna"), embedder=embedder)
    original_task = asyncio.Task
    result = await getattr(judge, metric)(_ITEM, context)
    assert result == {"score": expected}
    if metric == "answer_correctness":
        assert embedder.texts == ["Paris is the capital of France.", "Paris is the capital of France."]
    assert asyncio.Task is original_task
    async with asyncio.timeout(1):
        await asyncio.sleep(0)
