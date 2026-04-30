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

"""Tests for content chunking utilities."""

import pytest

from fireflyframework_agentic.content.chunking import (
    BatchProcessor,
    Chunk,
    Chunker,
    DocumentSplitter,
    ImageTiler,
    TextChunker,
)


class TestTextChunker:
    def test_empty_input(self):
        chunker = TextChunker(chunk_size=100, chunk_overlap=0)
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_single_chunk(self):
        chunker = TextChunker(chunk_size=1000, chunk_overlap=0)
        text = "Hello world this is a short text"
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].index == 0
        assert chunks[0].total_chunks == 1

    def test_multiple_chunks_with_overlap(self):
        words = " ".join(f"word{i}" for i in range(100))
        chunker = TextChunker(chunk_size=50, chunk_overlap=10, tokens_per_word=1.0)
        chunks = chunker.chunk(words)
        assert len(chunks) > 1
        # First chunk has no overlap
        assert chunks[0].overlap_tokens == 0
        # Subsequent chunks have overlap
        for c in chunks[1:]:
            assert c.overlap_tokens == 10

    def test_sentence_strategy(self):
        text = "First sentence. Second sentence. Third sentence. Fourth one."
        chunker = TextChunker(chunk_size=5, chunk_overlap=0, strategy="sentence", tokens_per_word=1.0)
        chunks = chunker.chunk(text)
        assert len(chunks) >= 1
        assert all(c.total_chunks == len(chunks) for c in chunks)

    def test_paragraph_strategy(self):
        text = "Paragraph one text.\n\nParagraph two text.\n\nParagraph three text."
        chunker = TextChunker(chunk_size=5, chunk_overlap=0, strategy="paragraph", tokens_per_word=1.0)
        chunks = chunker.chunk(text)
        assert len(chunks) >= 1

    def test_overlap_must_be_less_than_size(self):
        with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
            TextChunker(chunk_size=100, chunk_overlap=100)

    def test_implements_chunker_protocol(self):
        chunker = TextChunker()
        assert isinstance(chunker, Chunker)


class TestDocumentSplitter:
    def test_split_by_page_break(self):
        text = "Document A content.\fDocument B content."
        splitter = DocumentSplitter()
        chunks = splitter.split(text)
        assert len(chunks) == 2
        assert "Document A" in chunks[0].content
        assert "Document B" in chunks[1].content

    def test_split_by_horizontal_rule(self):
        text = "Doc 1 content here.\n---\nDoc 2 content here."
        splitter = DocumentSplitter()
        chunks = splitter.split(text)
        assert len(chunks) == 2

    def test_min_length_filter(self):
        text = "A.\fReal document content here."
        splitter = DocumentSplitter(min_length=10)
        chunks = splitter.split(text)
        assert len(chunks) == 1
        assert "Real document" in chunks[0].content

    def test_metadata_has_type(self):
        text = "Doc A.\fDoc B content here."
        splitter = DocumentSplitter(min_length=5)
        chunks = splitter.split(text)
        for c in chunks:
            assert c.metadata.get("type") == "document_segment"


class TestImageTiler:
    def test_single_tile_small_image(self):
        tiler = ImageTiler(tile_width=1024, tile_height=1024, overlap=0)
        tiles = tiler.compute_tiles(512, 512)
        assert len(tiles) == 1
        assert tiles[0].metadata["x"] == 0
        assert tiles[0].metadata["y"] == 0
        assert tiles[0].metadata["width"] == 512
        assert tiles[0].metadata["height"] == 512

    def test_multiple_tiles_large_image(self):
        tiler = ImageTiler(tile_width=100, tile_height=100, overlap=0)
        tiles = tiler.compute_tiles(250, 250)
        assert len(tiles) == 9  # 3x3 grid

    def test_overlap_creates_more_tiles(self):
        tiler_no_overlap = ImageTiler(tile_width=100, tile_height=100, overlap=0)
        tiler_overlap = ImageTiler(tile_width=100, tile_height=100, overlap=50)
        tiles_no = tiler_no_overlap.compute_tiles(200, 200)
        tiles_yes = tiler_overlap.compute_tiles(200, 200)
        assert len(tiles_yes) >= len(tiles_no)

    def test_tile_metadata(self):
        tiler = ImageTiler(tile_width=100, tile_height=100, overlap=0)
        tiles = tiler.compute_tiles(100, 100)
        assert tiles[0].metadata["row"] == 0
        assert tiles[0].metadata["col"] == 0


class TestBatchProcessor:
    async def test_process_chunks(self):
        class MockAgent:
            async def run(self, prompt, **kwargs):
                class R:
                    output = f"processed:{prompt[:10]}"

                return R()

        chunks = [Chunk(content=f"chunk_{i}", index=i, total_chunks=3) for i in range(3)]
        processor = BatchProcessor(concurrency=2)
        results = await processor.process(MockAgent(), chunks)
        assert len(results) == 3
        assert all("processed:" in r for r in results)

    async def test_custom_aggregator(self):
        class MockAgent:
            async def run(self, prompt, **kwargs):
                class R:
                    output = "x"

                return R()

        chunks = [Chunk(content="a"), Chunk(content="b")]
        processor = BatchProcessor(result_aggregator=lambda r: "".join(r))
        result = await processor.process(MockAgent(), chunks)
        assert result == "xx"
