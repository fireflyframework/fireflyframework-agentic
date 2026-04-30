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

"""Content processing: chunking, compression, and batch operations.

This package provides utilities for splitting large content into manageable
chunks, compressing context to fit within token budgets, and processing
chunks through agents in batch.
"""

from fireflyframework_agentic.content.chunking import (
    BatchProcessor,
    Chunk,
    Chunker,
    DocumentSplitter,
    ImageTiler,
    TextChunker,
)
from fireflyframework_agentic.content.compression import (
    CompressionStrategy,
    ContextCompressor,
    MapReduceStrategy,
    SlidingWindowManager,
    SummarizationStrategy,
    TokenEstimator,
    TruncationStrategy,
)
from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker

__all__ = [
    "BatchProcessor",
    "Chunk",
    "Chunker",
    "CompressionStrategy",
    "ContextCompressor",
    "DocumentSplitter",
    "ImageTiler",
    "MarkdownChunker",
    "MapReduceStrategy",
    "SlidingWindowManager",
    "SummarizationStrategy",
    "TextChunker",
    "TokenEstimator",
    "TruncationStrategy",
]
