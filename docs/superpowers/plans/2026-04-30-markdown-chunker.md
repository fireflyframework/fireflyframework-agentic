# MarkdownChunker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `MarkdownChunker` class to the framework that splits markdown at heading boundaries, prepends a breadcrumb path to each chunk, and falls back to `TextChunker` for sections that exceed the token budget.

**Architecture:** A single new file `markdown_chunker.py` in `src/fireflyframework_agentic/content/` implements the `Chunker` protocol by tokenising with `markdown-it-py`, splitting at `heading_open` token boundaries, building a breadcrumb from the heading stack, and delegating oversized bodies to `TextChunker`. Changes to `pipeline.py`, `agent.py`, and `benchmark/runner.py` are purely mechanical wiring swaps.

**Tech Stack:** `markdown-it-py>=3.0`, existing `TextChunker` + `Chunk` from `chunking.py`, `pytest`.

---

## File Map

| File | Action |
|------|--------|
| `pyproject.toml` | Modify — add `markdown-it-py>=3.0` to `markitdown` extra |
| `src/fireflyframework_agentic/content/markdown_chunker.py` | Create — `MarkdownChunker` + `_Section` |
| `src/fireflyframework_agentic/content/__init__.py` | Modify — export `MarkdownChunker` |
| `src/fireflyframework_agentic/rag/ingest/pipeline.py` | Modify — widen `chunker: TextChunker` → `chunker: Chunker` |
| `examples/corpus_search/agent.py` | Modify — swap `TextChunker` to `MarkdownChunker` |
| `tests/examples/corpus_search/benchmark/runner.py` | Modify — swap `TextChunker` to `MarkdownChunker` |
| `tests/unit/content/test_markdown_chunker.py` | Create — 10 unit tests |

---

### Task 1: Add `markdown-it-py` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

  Find the `markitdown` entry (currently line 87):
  ```toml
  markitdown = ["markitdown[pdf,docx,pptx,xlsx]>=0.0.1a3"]
  ```
  Replace with:
  ```toml
  markitdown = [
      "markitdown[pdf,docx,pptx,xlsx]>=0.0.1a3",
      "markdown-it-py>=3.0",
  ]
  ```

- [ ] **Step 2: Verify the package resolves (it is already a transitive dep)**

  Run:
  ```bash
  uv sync --extra markitdown
  python -c "import markdown_it; print(markdown_it.__version__)"
  ```
  Expected: prints a version ≥ 3.0 with no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add pyproject.toml
  git commit -m "chore: add markdown-it-py>=3.0 to markitdown extra"
  ```

---

### Task 2: Write failing unit tests

**Files:**
- Create: `tests/unit/content/test_markdown_chunker.py`

- [ ] **Step 1: Create the test file**

  ```python
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

  """Unit tests for MarkdownChunker."""

  import pytest

  from fireflyframework_agentic.content.chunking import Chunker
  from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker


  def test_chunker_protocol():
      assert isinstance(MarkdownChunker(), Chunker)


  def test_single_h1_section():
      content = "# Title\n\nSome body text here."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      assert len(chunks) == 1
      assert chunks[0].metadata["breadcrumb"] == "Title"
      assert chunks[0].content == "Title\n\nSome body text here."


  def test_nested_headings_breadcrumb():
      content = "# H1\n\n## H2\n\n### H3\n\nBody text here."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      # H1 and H2 sections have empty bodies; only H3 produces a chunk
      assert len(chunks) == 1
      assert chunks[0].metadata["breadcrumb"] == "H1 > H2 > H3"
      assert chunks[0].content.startswith("H1 > H2 > H3\n\nBody text here.")


  def test_heading_resets_lower_levels():
      content = "# H1\n\nH1 body.\n\n## H2-A\n\nBody A.\n\n## H2-B\n\nBody B."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      chunk_a = next(c for c in chunks if "Body A" in c.content)
      chunk_b = next(c for c in chunks if "Body B" in c.content)
      assert chunk_a.metadata["breadcrumb"] == "H1 > H2-A"
      assert chunk_b.metadata["breadcrumb"] == "H1 > H2-B"


  def test_preamble_no_breadcrumb():
      content = "Intro text before any heading.\n\n# Title\n\nBody text."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      preamble = next(c for c in chunks if "Intro text" in c.content)
      assert preamble.metadata["breadcrumb"] == ""
      assert preamble.content == "Intro text before any heading."


  def test_code_block_not_split():
      content = "# Title\n\n```python\n# this is a comment\n## also not a heading\n```\n\nEnd text."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      assert len(chunks) == 1
      assert "# this is a comment" in chunks[0].content
      assert chunks[0].metadata["breadcrumb"] == "Title"


  def test_oversized_section_fallback():
      # 40 words * 1.33 ≈ 53 tokens > max_chunk_tokens=20
      body = " ".join(f"word{i}" for i in range(40))
      content = f"# Title\n\n{body}"
      chunker = MarkdownChunker(max_chunk_tokens=20, chunk_overlap=5)
      chunks = chunker.chunk(content)
      assert len(chunks) > 1
      for c in chunks:
          assert c.metadata["breadcrumb"] == "Title"
          assert c.content.startswith("Title\n\n")


  def test_empty_section_skipped():
      content = "# Empty heading\n\n# Non-empty heading\n\nSome body text here."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      assert len(chunks) == 1
      assert "Non-empty heading" in chunks[0].metadata["breadcrumb"]


  def test_metadata_breadcrumb_field():
      content = "# Section\n\nContent text."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      assert len(chunks) == 1
      assert chunks[0].metadata["breadcrumb"] == "Section"
      assert chunks[0].content == "Section\n\nContent text."


  def test_no_headings_plain_text():
      content = "Just some plain text with no markdown headings at all."
      chunker = MarkdownChunker()
      chunks = chunker.chunk(content)
      assert len(chunks) == 1
      assert chunks[0].content == content
      assert chunks[0].metadata["breadcrumb"] == ""
  ```

- [ ] **Step 2: Run to confirm all 10 tests fail with ImportError**

  Run:
  ```bash
  uv run pytest tests/unit/content/test_markdown_chunker.py -v 2>&1 | head -20
  ```
  Expected: `ImportError: cannot import name 'MarkdownChunker'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Commit the failing tests**

  ```bash
  git add tests/unit/content/test_markdown_chunker.py
  git commit -m "test(content): add failing unit tests for MarkdownChunker"
  ```

---

### Task 3: Implement `MarkdownChunker`

**Files:**
- Create: `src/fireflyframework_agentic/content/markdown_chunker.py`

- [ ] **Step 1: Create the implementation file**

  ```python
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

  """Structure-aware markdown chunker."""

  from __future__ import annotations

  from dataclasses import dataclass

  from markdown_it import MarkdownIt

  from fireflyframework_agentic.content.chunking import Chunk, TextChunker


  @dataclass
  class _Section:
      heading_stack: list[tuple[int, str]]  # [(level, title), ...]
      body: str


  class MarkdownChunker:
      """Split markdown at heading boundaries with breadcrumb prepend.

      Uses ``markdown-it-py`` to tokenise so that ``#`` characters inside
      fenced code blocks and tables are never treated as headings. Sections
      whose body exceeds *max_chunk_tokens* are split further by
      :class:`TextChunker` with the same breadcrumb prepended to every
      sub-chunk.
      """

      def __init__(
          self,
          *,
          max_chunk_tokens: int = 600,
          chunk_overlap: int = 80,
          min_body_tokens: int = 10,
          breadcrumb_separator: str = " > ",
      ) -> None:
          self._max_chunk_tokens = max_chunk_tokens
          self._chunk_overlap = chunk_overlap
          self._min_body_tokens = min_body_tokens
          self._breadcrumb_separator = breadcrumb_separator
          self._fallback = TextChunker(
              chunk_size=max_chunk_tokens,
              chunk_overlap=chunk_overlap,
          )

      def chunk(self, content: str) -> list[Chunk]:
          """Split *content* into :class:`Chunk` objects at heading boundaries."""
          sections = self._parse_sections(content)
          chunks: list[Chunk] = []
          for section in sections:
              chunks.extend(self._emit_chunks(section))
          for i, c in enumerate(chunks):
              c.index = i
              c.total_chunks = len(chunks)
          return chunks

      def _parse_sections(self, content: str) -> list[_Section]:
          tokens = MarkdownIt().parse(content)
          lines = content.splitlines()

          heading_locs: list[tuple[int, int, str]] = []
          i = 0
          while i < len(tokens):
              tok = tokens[i]
              if tok.type == "heading_open" and tok.map:
                  level = int(tok.tag[1])  # "h1" → 1
                  line_number = tok.map[0]
                  title = tokens[i + 1].content if i + 1 < len(tokens) and tokens[i + 1].type == "inline" else ""
                  heading_locs.append((line_number, level, title))
                  i += 2
              else:
                  i += 1

          sections: list[_Section] = []
          heading_stack: list[tuple[int, str]] = []

          first_line = heading_locs[0][0] if heading_locs else len(lines)
          preamble = "\n".join(lines[:first_line]).strip()
          if preamble:
              sections.append(_Section(heading_stack=[], body=preamble))

          for idx, (line_no, level, title) in enumerate(heading_locs):
              next_line = heading_locs[idx + 1][0] if idx + 1 < len(heading_locs) else len(lines)
              body = "\n".join(lines[line_no + 1 : next_line]).strip()
              heading_stack = [(lvl, ttl) for lvl, ttl in heading_stack if lvl < level]
              heading_stack.append((level, title))
              sections.append(_Section(heading_stack=list(heading_stack), body=body))

          return sections

      def _estimate_tokens(self, text: str) -> int:
          return max(1, int(len(text.split()) * 1.33))

      def _emit_chunks(self, section: _Section) -> list[Chunk]:
          if not section.body.strip():
              return []
          if self._estimate_tokens(section.body) < self._min_body_tokens:
              return []

          breadcrumb = self._breadcrumb_separator.join(title for _, title in section.heading_stack)

          def make_chunk(body: str) -> Chunk:
              content = f"{breadcrumb}\n\n{body}" if breadcrumb else body
              return Chunk(content=content, metadata={"breadcrumb": breadcrumb})

          if self._estimate_tokens(section.body) <= self._max_chunk_tokens:
              return [make_chunk(section.body)]

          return [make_chunk(sc.content) for sc in self._fallback.chunk(section.body)]
  ```

- [ ] **Step 2: Run tests and confirm all 10 pass**

  Run:
  ```bash
  uv run pytest tests/unit/content/test_markdown_chunker.py -v
  ```
  Expected: `10 passed`.

- [ ] **Step 3: Run the full unit-test suite to check for regressions**

  Run:
  ```bash
  uv run pytest tests/unit/ -q
  ```
  Expected: all passing, no regressions.

- [ ] **Step 4: Commit**

  ```bash
  git add src/fireflyframework_agentic/content/markdown_chunker.py
  git commit -m "feat(content): implement MarkdownChunker with heading-boundary splitting and breadcrumb prepend"
  ```

---

### Task 4: Export `MarkdownChunker` from the content package

**Files:**
- Modify: `src/fireflyframework_agentic/content/__init__.py`

- [ ] **Step 1: Add the import and `__all__` entry**

  In `src/fireflyframework_agentic/content/__init__.py`:

  After the existing import block (line 22–38), add:
  ```python
  from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker
  ```

  Add `"MarkdownChunker"` to `__all__` (keep the list sorted alphabetically):
  ```python
  __all__ = [
      "BatchProcessor",
      "Chunk",
      "Chunker",
      "CompressionStrategy",
      "ContextCompressor",
      "DocumentSplitter",
      "ImageTiler",
      "MapReduceStrategy",
      "MarkdownChunker",
      "SlidingWindowManager",
      "SummarizationStrategy",
      "TextChunker",
      "TokenEstimator",
      "TruncationStrategy",
  ]
  ```

- [ ] **Step 2: Verify the export is reachable**

  Run:
  ```bash
  python -c "from fireflyframework_agentic.content import MarkdownChunker; print(MarkdownChunker)"
  ```
  Expected: `<class 'fireflyframework_agentic.content.markdown_chunker.MarkdownChunker'>`.

- [ ] **Step 3: Commit**

  ```bash
  git add src/fireflyframework_agentic/content/__init__.py
  git commit -m "feat(content): export MarkdownChunker from package root"
  ```

---

### Task 5: Widen `pipeline.py` chunker type to `Chunker`

**Files:**
- Modify: `src/fireflyframework_agentic/rag/ingest/pipeline.py`

- [ ] **Step 1: Replace the import and the type annotation**

  In `src/fireflyframework_agentic/rag/ingest/pipeline.py`:

  Change line 23 from:
  ```python
  from fireflyframework_agentic.content.chunking import TextChunker
  ```
  to:
  ```python
  from fireflyframework_agentic.content.chunking import Chunker, TextChunker
  ```

  Change the `ingest_one` signature (line 63) from:
  ```python
  chunker: TextChunker,
  ```
  to:
  ```python
  chunker: Chunker,
  ```

- [ ] **Step 2: Run type check**

  Run:
  ```bash
  uv run pyright src/fireflyframework_agentic/rag/ingest/pipeline.py
  ```
  Expected: `0 errors`.

- [ ] **Step 3: Run the ingest unit tests**

  Run:
  ```bash
  uv run pytest tests/unit/pipeline/ -q
  ```
  Expected: all passing.

- [ ] **Step 4: Commit**

  ```bash
  git add src/fireflyframework_agentic/rag/ingest/pipeline.py
  git commit -m "refactor(ingest): widen chunker parameter type to Chunker protocol"
  ```

---

### Task 6: Swap `CorpusAgent` to use `MarkdownChunker`

**Files:**
- Modify: `examples/corpus_search/agent.py`

- [ ] **Step 1: Update the import**

  In `examples/corpus_search/agent.py`, find:
  ```python
  from fireflyframework_agentic.content.chunking import TextChunker
  ```
  Replace with:
  ```python
  from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker
  ```

- [ ] **Step 2: Update the constructor assignment**

  Find (line ~79):
  ```python
  self._chunker = TextChunker(chunk_size=600, chunk_overlap=80)
  ```
  Replace with:
  ```python
  self._chunker = MarkdownChunker(max_chunk_tokens=600, chunk_overlap=80)
  ```

- [ ] **Step 3: Run the corpus_search integration tests**

  Run:
  ```bash
  uv run pytest tests/unit/corpus_search/ -q
  ```
  Expected: all passing.

- [ ] **Step 4: Commit**

  ```bash
  git add examples/corpus_search/agent.py
  git commit -m "feat(corpus_search): use MarkdownChunker for structure-aware ingest"
  ```

---

### Task 7: Swap benchmark runner to use `MarkdownChunker`

**Files:**
- Modify: `tests/examples/corpus_search/benchmark/runner.py`

- [ ] **Step 1: Add the import**

  In `tests/examples/corpus_search/benchmark/runner.py`, find the existing `TextChunker` import. Add `MarkdownChunker` beside it (or replace it if `TextChunker` is no longer needed in this file):
  ```python
  from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker
  ```

- [ ] **Step 2: Replace the chunker instantiation**

  Search for `TextChunker(` in `runner.py`. Replace the call used when building the ingest pipeline with:
  ```python
  MarkdownChunker(max_chunk_tokens=200, chunk_overlap=30)
  ```
  (The benchmark uses a smaller token budget than production to keep the mechanics test deterministic and fast.)

- [ ] **Step 3: Remove the `TextChunker` import if it is now unused**

  Run:
  ```bash
  uv run ruff check tests/examples/corpus_search/benchmark/runner.py --select F401
  ```
  If `TextChunker` is reported as unused, remove its import line.

- [ ] **Step 4: Run the benchmark smoke test**

  Run:
  ```bash
  uv run pytest tests/unit/corpus_search/test_benchmark_smoke.py -v
  ```
  Expected: passes.

- [ ] **Step 5: Run the mechanics-mode benchmark**

  Run:
  ```bash
  uv run python tests/examples/corpus_search/benchmark/runner.py --mode mechanics
  ```
  Expected: completes with Hit@5 and MRR printed. Note the numbers — if they are higher than the current baseline in `runs/baseline.json`, update the baseline.

- [ ] **Step 6: Commit**

  ```bash
  git add tests/examples/corpus_search/benchmark/runner.py
  git commit -m "feat(benchmark): use MarkdownChunker in corpus-search benchmark runner"
  ```

---

## Final check

After all tasks are committed, run the full test suite and linters:

```bash
uv run pytest tests/unit/ -q
uv run ruff check .
uv run ruff format --check .
uv run pyright src/
```

All should pass before opening the PR.
