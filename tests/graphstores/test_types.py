from __future__ import annotations

from fireflyframework_agentic.graphstores import Edge, Node


class TestNode:
    def test_minimum_fields(self):
        node = Node(
            label="Person",
            key="sam-altman",
            properties={"name": "Sam Altman"},
            source_doc_id="doc-001",
            extractor_name="person",
            chunk_ids=["c0", "c1"],
        )
        assert node.label == "Person"
        assert node.properties["name"] == "Sam Altman"
        assert node.chunk_ids == ["c0", "c1"]

    def test_serialises_to_dict(self):
        node = Node(
            label="Entity",
            key="OpenAI",
            properties={"type": "Company"},
            source_doc_id="doc-001",
            extractor_name="generic",
            chunk_ids=[],
        )
        dumped = node.model_dump()
        assert dumped["properties"] == {"type": "Company"}
        assert dumped["chunk_ids"] == []


class TestEdge:
    def test_minimum_fields(self):
        edge = Edge(
            label="WORKS_AT",
            source_label="Person",
            source_key="sam-altman",
            target_label="Organization",
            target_key="openai",
            properties={"role": "CEO"},
            source_doc_id="doc-001",
            extractor_name="person",
        )
        assert edge.source_label == "Person"
        assert edge.target_key == "openai"
        assert edge.properties["role"] == "CEO"
