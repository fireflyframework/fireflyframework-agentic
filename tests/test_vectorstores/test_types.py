"""Tests for vector store data models."""

from __future__ import annotations

from fireflyframework_genai.vectorstores.types import (
    SearchFilter,
    SearchResult,
    VectorDocument,
)


class TestVectorDocument:
    def test_create_minimal(self):
        doc = VectorDocument(id="1", text="hello world")
        assert doc.id == "1"
        assert doc.embedding is None
        assert doc.metadata == {}
        assert doc.namespace == "default"

    def test_create_with_embedding(self):
        doc = VectorDocument(
            id="2",
            text="test",
            embedding=[0.1, 0.2, 0.3],
            metadata={"source": "test"},
            namespace="ns1",
        )
        assert doc.embedding == [0.1, 0.2, 0.3]
        assert doc.metadata["source"] == "test"


class TestSearchResult:
    def test_create(self):
        doc = VectorDocument(id="1", text="hello")
        result = SearchResult(document=doc, score=0.95)
        assert result.score == 0.95
        assert result.document.id == "1"


class TestSearchFilter:
    def test_create(self):
        f = SearchFilter(field="category", operator="eq", value="tech")
        assert f.field == "category"
        assert f.operator == "eq"
