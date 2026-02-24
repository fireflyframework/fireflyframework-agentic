"""Tests for ChromaDB vector store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fireflyframework_genai.vectorstores.types import SearchFilter, VectorDocument


class TestChromaVectorStore:
    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_upsert(self, mock_chromadb):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.Client.return_value = mock_client

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(collection_name="test")
        await store.upsert([VectorDocument(id="1", text="hello", embedding=[1.0, 0.0])])
        mock_collection.upsert.assert_called_once()
        call_kwargs = mock_collection.upsert.call_args
        assert call_kwargs[1]["ids"] == ["1"]
        assert call_kwargs[1]["documents"] == ["hello"]
        assert call_kwargs[1]["embeddings"] == [[1.0, 0.0]]

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_upsert_with_namespace(self, mock_chromadb):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.Client.return_value = mock_client

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(collection_name="test")
        await store.upsert(
            [VectorDocument(id="1", text="hi", embedding=[1.0])],
            namespace="custom_ns",
        )
        call_kwargs = mock_collection.upsert.call_args
        assert call_kwargs[1]["metadatas"] == [{"_namespace": "custom_ns"}]

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_search(self, mock_chromadb):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["1", "2"]],
            "documents": [["hello", "world"]],
            "metadatas": [[{"_namespace": "default"}, {"_namespace": "default", "tag": "test"}]],
            "distances": [[0.1, 0.3]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.Client.return_value = mock_client

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(collection_name="test")
        results = await store.search([1.0, 0.0], top_k=2)

        assert len(results) == 2
        assert results[0].document.id == "1"
        assert results[0].document.text == "hello"
        assert results[0].score == pytest.approx(0.9)
        assert results[1].document.id == "2"
        assert results[1].score == pytest.approx(0.7)
        # _namespace should be stripped from metadata
        assert "_namespace" not in results[0].document.metadata
        assert results[1].document.metadata == {"tag": "test"}

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_search_with_filters(self, mock_chromadb):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["1"]],
            "documents": [["hello"]],
            "metadatas": [[{"_namespace": "default", "type": "blog"}]],
            "distances": [[0.05]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.Client.return_value = mock_client

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(collection_name="test")
        results = await store.search(
            [1.0, 0.0],
            top_k=5,
            filters=[SearchFilter(field="type", operator="eq", value="blog")],
        )
        assert len(results) == 1
        # Verify the where clause included the filter
        call_kwargs = mock_collection.query.call_args
        assert call_kwargs[1]["where"]["type"] == "blog"
        assert call_kwargs[1]["where"]["_namespace"] == "default"

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_search_empty_results(self, mock_chromadb):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.Client.return_value = mock_client

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(collection_name="test")
        results = await store.search([1.0, 0.0], top_k=5)
        assert results == []

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_delete(self, mock_chromadb):
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.Client.return_value = mock_client

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(collection_name="test")
        await store.delete(["1", "2"])
        mock_collection.delete.assert_called_once_with(ids=["1", "2"], where={"_namespace": "default"})

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb")
    async def test_custom_client(self, mock_chromadb):
        mock_collection = MagicMock()
        custom_client = MagicMock()
        custom_client.get_or_create_collection.return_value = mock_collection

        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        ChromaVectorStore(collection_name="my_coll", client=custom_client)
        # Should use the custom client, not create a new one
        mock_chromadb.Client.assert_not_called()
        custom_client.get_or_create_collection.assert_called_once_with(name="my_coll")

    @patch("fireflyframework_genai.vectorstores.chroma_store.chromadb", None)
    async def test_import_error_when_chromadb_not_installed(self):
        from fireflyframework_genai.vectorstores.chroma_store import ChromaVectorStore

        with pytest.raises(ImportError, match="chromadb"):
            ChromaVectorStore()
