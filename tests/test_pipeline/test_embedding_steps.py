"""Tests for EmbeddingStep and RetrievalStep pipeline steps."""

from __future__ import annotations

from fireflyframework_genai.embeddings.base import BaseEmbedder
from fireflyframework_genai.embeddings.types import EmbeddingResult
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.pipeline.steps import EmbeddingStep, RetrievalStep
from fireflyframework_genai.vectorstores.memory_store import InMemoryVectorStore
from fireflyframework_genai.vectorstores.types import VectorDocument


class _FakeEmbedder(BaseEmbedder):
    def __init__(self):
        super().__init__(model="fake", dimensions=3)

    async def _embed_batch(self, texts, **kwargs):
        return [[float(len(t)), 0.0, 1.0] for t in texts]


class TestEmbeddingStep:
    async def test_execute_single_text(self):
        embedder = _FakeEmbedder()
        step = EmbeddingStep(embedder=embedder)
        ctx = PipelineContext(inputs="hello")
        result = await step.execute(ctx, {"input": "hello"})
        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 1

    async def test_execute_list_of_texts(self):
        embedder = _FakeEmbedder()
        step = EmbeddingStep(embedder=embedder)
        ctx = PipelineContext(inputs="")
        result = await step.execute(ctx, {"input": ["hello", "world"]})
        assert len(result.embeddings) == 2

    async def test_custom_input_key(self):
        embedder = _FakeEmbedder()
        step = EmbeddingStep(embedder=embedder, input_key="texts")
        ctx = PipelineContext(inputs="")
        result = await step.execute(ctx, {"texts": ["hello"]})
        assert len(result.embeddings) == 1


class TestRetrievalStep:
    async def test_execute_retrieves(self):
        embedder = _FakeEmbedder()
        store = InMemoryVectorStore(embedder=embedder)
        docs = [
            VectorDocument(id="1", text="python programming", embedding=[18.0, 0.0, 1.0]),
            VectorDocument(id="2", text="javascript", embedding=[10.0, 0.0, 1.0]),
        ]
        await store.upsert(docs)

        step = RetrievalStep(store=store, embedder=embedder, top_k=1)
        ctx = PipelineContext(inputs="")
        results = await step.execute(ctx, {"input": "python"})
        assert len(results) == 1

    async def test_custom_top_k(self):
        embedder = _FakeEmbedder()
        store = InMemoryVectorStore(embedder=embedder)
        docs = [VectorDocument(id=str(i), text=f"doc{i}", embedding=[float(i), 0.0, 1.0]) for i in range(5)]
        await store.upsert(docs)

        step = RetrievalStep(store=store, embedder=embedder, top_k=3)
        ctx = PipelineContext(inputs="")
        results = await step.execute(ctx, {"input": "test"})
        assert len(results) == 3
