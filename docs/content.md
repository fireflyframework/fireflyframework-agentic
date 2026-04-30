# Content Processing Guide

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

The Content module provides utilities for splitting, chunking, and compressing large
inputs before they are sent to LLM agents. This is essential for processing documents,
images, and other artefacts that exceed a model's context window.

---

## Chunking (`content.chunking`)

### TextChunker

`TextChunker` splits a text string into overlapping chunks using one of three strategies:

- **token** (default) -- Splits by estimated token count.
- **sentence** -- Splits at sentence boundaries.
- **paragraph** -- Splits at paragraph boundaries (double newlines).

```python
from fireflyframework_agentic.content.chunking import TextChunker

chunker = TextChunker(chunk_size=4000, chunk_overlap=200, strategy="token")
chunks = chunker.chunk(long_text)
for c in chunks:
    print(f"Chunk {c.index}/{c.total_chunks}: {len(c.content)} chars")
```

Each chunk is a `Chunk` model with `content`, `index`, `total_chunks`, `overlap_tokens`,
and an open `metadata` dictionary.

### DocumentSplitter

`DocumentSplitter` splits multi-document inputs at page breaks (`\f`) or horizontal
rules (`---`). Segments shorter than `min_length` are discarded.

```python
from fireflyframework_agentic.content.chunking import DocumentSplitter

splitter = DocumentSplitter(min_length=50)
segments = splitter.split(raw_text)
```

### ImageTiler

`ImageTiler` computes tile coordinates for large images, enabling VLM processing
of high-resolution images that exceed the model's pixel budget.

```python
from fireflyframework_agentic.content.chunking import ImageTiler

tiler = ImageTiler(tile_width=1024, tile_height=1024, overlap=128)
tiles = tiler.compute_tiles(image_width=4096, image_height=3072)
```

Each tile is a `Chunk` whose `metadata` contains `x`, `y`, `width`, `height`, `row`,
and `col` fields.

### BatchProcessor

`BatchProcessor` sends a list of chunks through an agent concurrently, with configurable
parallelism and an optional result aggregator.

```python
from fireflyframework_agentic.content.chunking import BatchProcessor

processor = BatchProcessor(concurrency=4)
results = await processor.process(agent, chunks)
```

---

## Compression (`content.compression`)

### TokenEstimator

`TokenEstimator` estimates the number of tokens in a string using a configurable
words-to-tokens ratio (default: `1.33`).

```python
from fireflyframework_agentic.content.compression import TokenEstimator

estimator = TokenEstimator()
tokens = estimator.estimate("Hello world, this is a test.")
```

### ContextCompressor

`ContextCompressor` reduces text to fit within a target token budget. It supports
pluggable strategies:

- **TruncationStrategy** -- Hard truncation at the token limit.
- **SummarizationStrategy** -- Uses an LLM agent to summarise.
- **MapReduceStrategy** -- Chunks the text, summarises each chunk, then merges.

```python
from fireflyframework_agentic.content.compression import (
    ContextCompressor,
    TruncationStrategy,
)

compressor = ContextCompressor(strategy=TruncationStrategy())
compressed = await compressor.compress(long_text, max_tokens=2000)
```

### SlidingWindowManager

`SlidingWindowManager` maintains a sliding window over a stream of messages or chunks,
keeping total token usage within a budget by evicting the oldest items.

```python
from fireflyframework_agentic.content.compression import SlidingWindowManager

window = SlidingWindowManager(max_tokens=8000)
window.add("First message")
window.add("Second message")
current_context = window.get_context()
```
