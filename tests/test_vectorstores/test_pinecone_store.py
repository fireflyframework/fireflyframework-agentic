"""Tests for Pinecone vector store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fireflyframework_genai.vectorstores.types import SearchFilter, VectorDocument


class TestPineconeVectorStore:
    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_upsert(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        await store.upsert(
            [VectorDocument(id="1", text="hello", embedding=[1.0, 0.0])],
            namespace="ns1",
        )
        mock_index.upsert.assert_called_once()
        call_kwargs = mock_index.upsert.call_args
        assert call_kwargs[1]["namespace"] == "ns1"
        vectors = call_kwargs[1]["vectors"]
        assert len(vectors) == 1
        assert vectors[0]["id"] == "1"
        assert vectors[0]["values"] == [1.0, 0.0]
        assert vectors[0]["metadata"]["_text"] == "hello"

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_upsert_with_metadata(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        await store.upsert(
            [
                VectorDocument(
                    id="1",
                    text="hello",
                    embedding=[1.0, 0.0],
                    metadata={"type": "blog"},
                )
            ]
        )
        vectors = mock_index.upsert.call_args[1]["vectors"]
        assert vectors[0]["metadata"]["type"] == "blog"
        assert vectors[0]["metadata"]["_text"] == "hello"

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_search(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_index.query.return_value = {
            "matches": [
                {"id": "1", "score": 0.95, "metadata": {"_text": "hello", "tag": "a"}},
                {"id": "2", "score": 0.80, "metadata": {"_text": "world"}},
            ]
        }
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        results = await store.search([1.0, 0.0], top_k=2, namespace="ns1")

        assert len(results) == 2
        assert results[0].document.id == "1"
        assert results[0].document.text == "hello"
        assert results[0].score == 0.95
        assert results[0].document.metadata == {"tag": "a"}
        # _text should be stripped from metadata
        assert "_text" not in results[0].document.metadata
        assert results[1].document.id == "2"
        assert results[1].document.text == "world"

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_search_with_eq_filter(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_index.query.return_value = {"matches": []}
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        await store.search(
            [1.0, 0.0],
            top_k=5,
            filters=[SearchFilter(field="type", operator="eq", value="blog")],
        )
        call_kwargs = mock_index.query.call_args[1]
        assert call_kwargs["filter"] == {"type": "blog"}

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_search_with_in_filter(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_index.query.return_value = {"matches": []}
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        await store.search(
            [1.0, 0.0],
            top_k=5,
            filters=[SearchFilter(field="type", operator="in", value=["a", "b"])],
        )
        call_kwargs = mock_index.query.call_args[1]
        assert call_kwargs["filter"] == {"type": {"$in": ["a", "b"]}}

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_search_empty_results(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_index.query.return_value = {"matches": []}
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        results = await store.search([1.0, 0.0], top_k=5)
        assert results == []

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone")
    async def test_delete(self, mock_pinecone_cls):
        mock_index = MagicMock()
        mock_pc = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_pinecone_cls.return_value = mock_pc

        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        store = PineconeVectorStore(index_name="test-index", api_key="fake-key")
        await store.delete(["1", "2"], namespace="ns1")
        mock_index.delete.assert_called_once_with(ids=["1", "2"], namespace="ns1")

    @patch("fireflyframework_genai.vectorstores.pinecone_store.Pinecone", None)
    async def test_import_error_when_pinecone_not_installed(self):
        from fireflyframework_genai.vectorstores.pinecone_store import PineconeVectorStore

        with pytest.raises(ImportError, match="pinecone"):
            PineconeVectorStore(index_name="test")
