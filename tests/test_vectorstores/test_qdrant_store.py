"""Tests for Qdrant vector store."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fireflyframework_genai.vectorstores.types import SearchFilter, VectorDocument


class TestQdrantVectorStore:
    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.PointStruct")
    async def test_upsert(self, mock_point_struct, mock_client_cls):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_point_struct.side_effect = lambda **kw: MagicMock(**kw)

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(collection_name="test")
        await store.upsert(
            [VectorDocument(id="1", text="hello", embedding=[1.0, 0.0])],
            namespace="ns1",
        )
        mock_client.upsert.assert_called_once()
        call_kwargs = mock_client.upsert.call_args[1]
        assert call_kwargs["collection_name"] == "test"
        assert len(call_kwargs["points"]) == 1

    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.PointStruct")
    async def test_upsert_with_metadata(self, mock_point_struct, mock_client_cls):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        captured_kwargs = {}

        def capture_point(**kw):
            captured_kwargs.update(kw)
            return MagicMock(**kw)

        mock_point_struct.side_effect = capture_point

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(collection_name="test")
        await store.upsert(
            [
                VectorDocument(
                    id="1",
                    text="hello",
                    embedding=[1.0, 0.0],
                    metadata={"type": "blog"},
                )
            ],
            namespace="custom_ns",
        )
        assert captured_kwargs["payload"]["text"] == "hello"
        assert captured_kwargs["payload"]["_namespace"] == "custom_ns"
        assert captured_kwargs["payload"]["type"] == "blog"

    @patch("fireflyframework_genai.vectorstores.qdrant_store.Filter")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.MatchValue")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.FieldCondition")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    async def test_search(self, mock_client_cls, mock_fc, mock_mv, mock_filter):
        mock_point1 = MagicMock()
        mock_point1.id = "1"
        mock_point1.payload = {"text": "hello", "_namespace": "default", "tag": "a"}
        mock_point1.score = 0.95

        mock_point2 = MagicMock()
        mock_point2.id = "2"
        mock_point2.payload = {"text": "world", "_namespace": "default"}
        mock_point2.score = 0.80

        mock_client = AsyncMock()
        mock_client.search.return_value = [mock_point1, mock_point2]
        mock_client_cls.return_value = mock_client

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(collection_name="test")
        results = await store.search([1.0, 0.0], top_k=2)

        assert len(results) == 2
        assert results[0].document.id == "1"
        assert results[0].document.text == "hello"
        assert results[0].score == 0.95
        assert results[0].document.metadata == {"tag": "a"}
        # _namespace and text should be stripped from metadata
        assert "_namespace" not in results[0].document.metadata
        assert "text" not in results[0].document.metadata
        assert results[1].document.id == "2"
        assert results[1].document.text == "world"

    @patch("fireflyframework_genai.vectorstores.qdrant_store.Filter")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.MatchValue")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.FieldCondition")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    async def test_search_with_filters(self, mock_client_cls, mock_fc, mock_mv, mock_filter):
        mock_client = AsyncMock()
        mock_client.search.return_value = []
        mock_client_cls.return_value = mock_client

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(collection_name="test")
        await store.search(
            [1.0, 0.0],
            top_k=5,
            filters=[SearchFilter(field="type", operator="eq", value="blog")],
        )
        # Should have created 2 FieldConditions: _namespace + type filter
        assert mock_fc.call_count == 2

    @patch("fireflyframework_genai.vectorstores.qdrant_store.Filter")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.MatchValue")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.FieldCondition")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    async def test_search_empty_results(self, mock_client_cls, mock_fc, mock_mv, mock_filter):
        mock_client = AsyncMock()
        mock_client.search.return_value = []
        mock_client_cls.return_value = mock_client

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(collection_name="test")
        results = await store.search([1.0, 0.0], top_k=5)
        assert results == []

    @patch("fireflyframework_genai.vectorstores.qdrant_store.PointIdsList")
    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    async def test_delete(self, mock_client_cls, mock_points_list):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(collection_name="test")
        await store.delete(["1", "2"])
        mock_client.delete.assert_called_once()
        call_kwargs = mock_client.delete.call_args[1]
        assert call_kwargs["collection_name"] == "test"
        mock_points_list.assert_called_once_with(points=["1", "2"])

    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient", None)
    async def test_import_error_when_qdrant_not_installed(self):
        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        with pytest.raises(ImportError, match="qdrant-client"):
            QdrantVectorStore()

    @patch("fireflyframework_genai.vectorstores.qdrant_store.AsyncQdrantClient")
    async def test_constructor_params(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fireflyframework_genai.vectorstores.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(
            collection_name="my_coll",
            url="http://custom:6333",
            api_key="secret",
            vector_size=768,
        )
        mock_client_cls.assert_called_once_with(url="http://custom:6333", api_key="secret")
        assert store._collection_name == "my_coll"
        assert store._vector_size == 768
