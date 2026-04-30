from __future__ import annotations

from pathlib import Path

import pytest

from fireflyframework_agentic.content.loaders import MarkitdownLoader

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_html_returns_markdown_with_metadata():
    loader = MarkitdownLoader()
    doc = loader.load(FIXTURES / "sample.html")
    assert "Hello" in doc.content
    assert "sample HTML document" in doc.content
    assert doc.metadata["source_path"].endswith("sample.html")
    assert doc.metadata["mime_type"]


def test_load_plain_text_passes_through():
    loader = MarkitdownLoader()
    doc = loader.load(FIXTURES / "sample.txt")
    assert "plain text fixture" in doc.content


def test_load_missing_file_raises():
    loader = MarkitdownLoader()
    with pytest.raises(FileNotFoundError):
        loader.load(FIXTURES / "does-not-exist.pdf")
