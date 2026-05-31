# Content Processing Guide

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The Content module provides utilities for splitting, chunking, and compressing large
inputs before they are sent to LLM agents. This is essential for processing documents,
images, and other artefacts that exceed a model's context window. It also includes a
binary normalisation subsystem (the `[binary]` extra) that turns raw uploaded files
(PDF, Office, images, archives, emails) into consumer-ready artifacts, and a content
sources layer for discovering files to ingest.

All chunking and compression symbols are canonically re-exported from the package root,
so the shortest import is `from fireflyframework_agentic.content import TextChunker`. The
deeper submodule paths (`content.chunking`, `content.compression`,
`content.markdown_chunker`) remain valid.

---

## Chunking (`content.chunking`)

### TextChunker

`TextChunker` splits a text string into overlapping chunks using one of three strategies:

- **token** (default) -- Splits by estimated token count.
- **sentence** -- Splits at sentence boundaries.
- **paragraph** -- Splits at paragraph boundaries (double newlines).

All `TextChunker` constructor arguments are keyword-only.

```python
from fireflyframework_agentic.content import TextChunker

chunker = TextChunker(chunk_size=4000, chunk_overlap=200, strategy="token")
chunks = chunker.chunk(long_text)
for c in chunks:
    print(f"Chunk {c.index}/{c.total_chunks}: {len(c.content)} chars")
```

Each chunk is a `Chunk` model with `content`, `index`, `total_chunks`, `source_start`,
`source_end`, `overlap_tokens`, and an open `metadata` dictionary. The `source_start` /
`source_end` fields record the chunk's offset in the original content (character offsets
for text, pixel-derived offsets for image tiles) so consumers can reconstruct provenance.

### DocumentSplitter

`DocumentSplitter` splits multi-document inputs at the boundaries matched by its
`separator` regex. The default separator is `r"\f|\n-{3,}\n|\n={3,}\n"`, which splits on
form-feed (`\f`) characters, a line of three or more dashes (`---`), and a line of three
or more equals signs (`===`). Segments shorter than `min_length` characters (default
`10`) are discarded. Both constructor arguments are keyword-only.

```python
from fireflyframework_agentic.content import DocumentSplitter

splitter = DocumentSplitter(min_length=50)
segments = splitter.split(raw_text)
```

Each segment is a `Chunk` whose `metadata` carries `{"type": "document_segment"}`.

### MarkdownChunker

`MarkdownChunker` is a structure-aware chunker that splits markdown at heading
boundaries and prepends the heading breadcrumb (e.g. `Guide > Setup > Install`) to every
chunk. It tokenises with `markdown-it-py` so that `#` characters inside fenced code
blocks and tables are never mistaken for headings. Sections whose body exceeds
`max_chunk_tokens` are split further by an internal `TextChunker`, and a final pass
hard-enforces the token budget against the real `tiktoken` BPE tokeniser (`cl100k_base`)
when it is installed, recursively splitting any body whose word-count estimate undercounts
the true token count (markdown tables in particular). All arguments are keyword-only.

```python
from fireflyframework_agentic.content import MarkdownChunker

chunker = MarkdownChunker(
    max_chunk_tokens=600,
    chunk_overlap=80,
    min_body_tokens=10,
    breadcrumb_separator=" > ",
)
chunks = chunker.chunk(markdown_text)
```

Each chunk's `metadata` carries the `breadcrumb` string for the section it came from.

### ImageTiler

`ImageTiler` computes tile coordinates for large images, enabling VLM processing
of high-resolution images that exceed the model's pixel budget.

All `ImageTiler` constructor arguments are keyword-only.

```python
from fireflyframework_agentic.content import ImageTiler

tiler = ImageTiler(tile_width=1024, tile_height=1024, overlap=128)
tiles = tiler.compute_tiles(image_width=4096, image_height=3072)
```

Each tile is a `Chunk` whose `metadata` contains `x`, `y`, `width`, `height`, `row`,
and `col` fields.

### BatchProcessor

`BatchProcessor` sends a list of chunks through an agent concurrently, with configurable
parallelism and an optional result aggregator.

`BatchProcessor` constructor arguments are keyword-only. `process()` accepts an optional
`prompt_template` format string (default `"{content}"`) where `{content}`, `{index}`,
`{total_chunks}`, and any chunk-metadata fields are interpolated, plus extra `**kwargs`
forwarded to `agent.run()`.

```python
from fireflyframework_agentic.content import BatchProcessor

processor = BatchProcessor(concurrency=4)
results = await processor.process(agent, chunks)
```

### Chunker protocol

`Chunker` is a runtime-checkable `Protocol` defining the pluggable chunking contract:
a single `chunk(content: str) -> list[Chunk]` method. `TextChunker`, `DocumentSplitter`,
and `MarkdownChunker` all satisfy it, so any of them can be passed where a `Chunker` is
expected.

---

## Compression (`content.compression`)

### TokenEstimator

`TokenEstimator` estimates the number of tokens in a string. By default it uses a
configurable words-to-tokens heuristic (`tokens_per_word`, default `1.33`). When
`tiktoken` is installed and an `encoding_name` is supplied (e.g. `"cl100k_base"`), it
uses the exact tokenizer instead, falling back to the heuristic if `tiktoken` is absent.
Constructor arguments are keyword-only. The `fits(text, max_tokens)` helper returns
`True` when the estimate is within budget.

```python
from fireflyframework_agentic.content import TokenEstimator

estimator = TokenEstimator(encoding_name="cl100k_base")  # exact, if tiktoken installed
tokens = estimator.estimate("Hello world, this is a test.")
within_budget = estimator.fits("...", max_tokens=4000)
```

### ContextCompressor

`ContextCompressor` reduces text to fit within a target token budget. If the text
already fits (per its `TokenEstimator`), `compress()` returns it unchanged; otherwise it
delegates to a pluggable strategy. The strategy is the first positional argument; an
optional `estimator` keyword overrides the default `TokenEstimator`. Note that
`compress()` is **async** and must be awaited.

- **TruncationStrategy** -- Hard truncation that keeps the beginning of the text.
  Keyword-only `tokens_per_word` and `suffix` (no `max_tokens` constructor argument;
  the limit is passed to `compress(text, max_tokens)`).
- **SummarizationStrategy** -- Uses an LLM agent to summarise. Takes the `agent` as its
  first positional argument plus a keyword-only `system_instruction`.
- **MapReduceStrategy** -- Chunks the text, summarises each chunk, then merges (with a
  final reduction pass if the merged summary is still over budget). Takes the `agent`
  positionally plus keyword-only `chunk_size` / `chunk_overlap`.

```python
from fireflyframework_agentic.content import ContextCompressor, TruncationStrategy

compressor = ContextCompressor(TruncationStrategy())
compressed = await compressor.compress(long_text, max_tokens=2000)
```

All three built-in strategies satisfy the runtime-checkable `CompressionStrategy`
protocol, whose single method is `async compress(text: str, max_tokens: int) -> str`.
Implement that contract to plug in a custom strategy.

### SlidingWindowManager

`SlidingWindowManager` maintains a sliding window over a stream of messages or chunks,
keeping total token usage within a budget by evicting the oldest items. Constructor
arguments are keyword-only and `max_tokens` defaults to `128_000`. It exposes the
`segment_count` and `estimated_tokens` properties for introspection and a `clear()`
method to reset the window.

```python
from fireflyframework_agentic.content import SlidingWindowManager

window = SlidingWindowManager(max_tokens=8000)
window.add("First message")
window.add("Second message")
current_context = window.get_context()
print(window.segment_count, window.estimated_tokens)
```

---

## Content sources (`content.sources`)

The sources layer abstracts *where* files come from before they are normalised and
chunked. `ContentSource` is a runtime-checkable `Protocol` describing a cursor-based
discovery contract: `list_changed(since)` yields `RawFile` descriptors, `fetch(file)`
downloads one to a local `Path`, and `current_cursor()` / `pending_cursor()` /
`commit_delta(cursor)` manage incremental delta tracking. Each `RawFile` carries
`source_id`, `name`, `mime_type`, `size_bytes`, `etag`, `fetched_at`, and a `metadata`
dict.

`LocalFolderSource` is the built-in filesystem implementation, configured by
`LocalFolderSourceConfig` (a `folder` path, an `include_hidden` flag, and an optional
`exclude_predicate` callable). It walks a directory tree and yields a `RawFile` per file.

```python
from fireflyframework_agentic.content.sources import (
    LocalFolderSource,
    LocalFolderSourceConfig,
)

source = LocalFolderSource(LocalFolderSourceConfig(folder="/data/corpus"))
async for raw in source.list_changed(since=None):
    path = await source.fetch(raw)
```

---

## Binary normalisation (`content.binary`, `[binary]` extra)

The binary subsystem turns a raw uploaded file (PDF, DOCX, XLSX, images, archives,
emails, ...) into one or more consumer-ready `BinaryArtifact` rows for a downstream
document loader or multimodal LLM. It is host-agnostic: configure it with a
`BinaryConfig` and inject plain handler classes -- no DI framework required. Heavy
third-party dependencies (`pypdf`, `Pillow`, `pillow-heif`, `cairosvg`, `py7zr`,
`extract-msg`) ship in the `fireflyframework-agentic[binary]` extra and are imported
lazily; a missing dependency surfaces as a typed error only when the relevant format is
actually encountered.

`BinaryNormalizer.normalise()` sniffs the real media type from magic bytes (never
trusting the declared Content-Type or extension), routes to the right handler, and fans
out into a list of `BinaryArtifact`, each carrying a `derived_from` ancestry tuple so a
member of an archive or email can be traced back to its parent bundle. Recursion depth
and total fan-out are bounded by `BinaryConfig`.

```python
from fireflyframework_agentic.content.binary import (
    BinaryConfig,
    BinaryNormalizer,
    build_office_converter,
)

config = BinaryConfig(office_converter="gotenberg", wrap_text_as_pdf=True)
normalizer = BinaryNormalizer(config=config, office=build_office_converter(config))
artifacts = await normalizer.normalise(raw_bytes, declared_media_type="application/pdf", filename="report.pdf")
for art in artifacts:
    print(art.kind, art.media_type, art.page_count, art.derived_from)
```

Key components:

- **`BinaryArtifact`** -- frozen output unit: `bytes`, `media_type`, `filename`, `kind`
  (canonical token such as `"pdf"`, `"image"`, `"docx"`, `"archive"`), `page_count`, and
  `derived_from`.
- **`BinaryConfig`** -- frozen tunables: `normalize_enabled`, `max_bytes`,
  `max_recursion_depth`, `max_expanded_files`, `max_uncompressed_bytes`,
  `wrap_text_as_pdf`, `email_render_header`, `office_converter`
  (`"none"`/`"gotenberg"`/`"libreoffice"`), plus Gotenberg/LibreOffice URL, path, and
  timeout fields.
- **`PdfGuard`** -- pre-flight integrity check; rejects encrypted PDFs
  (`EncryptedPdfError`) and corrupt/truncated PDFs (`CorruptPdfError`).
- **`ImageNormalizer`** / **`NormalisedImage`** -- converts HEIC/HEIF/AVIF/TIFF/BMP/SVG to
  PNG (or multi-page PDF for multi-frame TIFF); passes through PNG/JPEG/GIF/WebP.
- **`ArchiveUnpacker`** / **`EmailUnpacker`** -- fan out archives and emails into member
  files for recursive normalisation.
- **Office converters** -- `OfficeConverter` is the protocol;
  `build_office_converter(config)` returns `GotenbergConverter` (HTTP sidecar),
  `LibreOfficeConverter` (`soffice` subprocess), or `NoOpOfficeConverter` (the default
  pass-through) based on `BinaryConfig.office_converter`. `OFFICE_MEDIA_TYPES` is the
  frozenset of renderable MIME types.
- **`sniff_media_type(data, default=..., filename=...)`** -- magic-byte media-type
  detection used throughout the pipeline.
- **Error types** -- `BinaryNormalizationError` (base), `BinaryTooLargeError`,
  `UnsupportedBinaryError`, `CorruptPdfError`, `EncryptedPdfError`,
  `OfficeConversionError`, `ImageConversionError`, `ArchiveExtractionError`,
  `EmailParseError`, `BinaryFanoutError`.
