# Copyright 2026 Firefly Software Foundation
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

from fireflyframework_agentic.content.chunking import Chunker
from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker


def test_chunker_protocol():
    assert isinstance(MarkdownChunker(), Chunker)


def test_single_h1_section():
    content = "# Title\n\nSome body text here that is long enough."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    assert len(chunks) == 1
    assert chunks[0].metadata["breadcrumb"] == "Title"
    assert chunks[0].content == "Title\n\nSome body text here that is long enough."


def test_nested_headings_breadcrumb():
    content = "# H1\n\n## H2\n\n### H3\n\nBody text here that is long enough to pass."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    # H1 and H2 have no body text so they produce no chunks.
    # H3 breadcrumb still includes the full ancestor path.
    assert len(chunks) == 1
    assert chunks[0].metadata["breadcrumb"] == "H1 > H2 > H3"
    assert chunks[0].content.startswith("H1 > H2 > H3\n\nBody text here that is long enough to pass.")


def test_heading_resets_lower_levels():
    content = "# H1\n\nH1 body text here that is long enough.\n\n## H2-A\n\nBody A text here that is long enough.\n\n## H2-B\n\nBody B text here that is long enough."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    chunk_a = next(c for c in chunks if "Body A" in c.content)
    chunk_b = next(c for c in chunks if "Body B" in c.content)
    assert chunk_a.metadata["breadcrumb"] == "H1 > H2-A"
    assert chunk_b.metadata["breadcrumb"] == "H1 > H2-B"


def test_preamble_no_breadcrumb():
    content = "Intro text before any heading that is long enough.\n\n# Title\n\nBody text that is long enough here."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    preamble = next(c for c in chunks if "Intro text" in c.content)
    assert preamble.metadata["breadcrumb"] == ""
    assert preamble.content == "Intro text before any heading that is long enough."


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
    content = "# Empty heading\n\n# Non-empty heading\n\nSome body text here that is long enough."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    assert len(chunks) == 1
    assert "Non-empty heading" in chunks[0].metadata["breadcrumb"]


def test_metadata_breadcrumb_field():
    content = "# Section\n\nContent text that is long enough to pass here."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    assert len(chunks) == 1
    assert chunks[0].metadata["breadcrumb"] == "Section"
    assert chunks[0].content == "Section\n\nContent text that is long enough to pass here."


def test_no_headings_plain_text():
    content = "Just some plain text with no markdown headings at all."
    chunker = MarkdownChunker()
    chunks = chunker.chunk(content)
    assert len(chunks) == 1
    assert chunks[0].content == content
    assert chunks[0].metadata["breadcrumb"] == ""


def test_giant_table_is_hard_split_under_max_tokens():
    """Markdown tables can have a real BPE token count 5–20× higher than the
    word-count heuristic. Without the hard-split safety pass, a single huge
    table chunk gets through the word-bounded fallback and explodes when the
    embedder actually counts BPE tokens. Verify the safety pass keeps every
    chunk under max_chunk_tokens by tiktoken's own count.
    """
    try:
        import tiktoken  # noqa: F401
    except ImportError:
        import pytest

        pytest.skip("tiktoken not installed; safety pass is a no-op without it")

    # Build a "table" big enough that the word-count heuristic underestimates
    # by enough to push a single chunk past 600 BPE tokens.
    rows = ["| 1.234 | 5.678 | 9.012 | 3.456 | 7.890 | 0.123 | 4.567 | 8.901 |"] * 250
    content = "# Stats\n\n| a | b | c | d | e | f | g | h |\n|---|---|---|---|---|---|---|---|\n" + "\n".join(rows)

    chunker = MarkdownChunker(max_chunk_tokens=600)
    chunks = chunker.chunk(content)

    from fireflyframework_agentic.content.markdown_chunker import _accurate_token_count

    for c in chunks:
        n = _accurate_token_count(c.content)
        assert n is not None
        # Allow a tiny slack for the breadcrumb prefix; the hard split
        # bounds chunk content but not the prepended breadcrumb header.
        assert n <= 600 + 50, f"chunk has {n} BPE tokens, exceeds 600+50 budget"
