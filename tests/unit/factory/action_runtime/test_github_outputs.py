# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for github_outputs.write_output."""
from __future__ import annotations

from pathlib import Path

import pytest

from fireflyframework_agentic.factory.action_runtime.github_outputs import (
    write_output,
)


def test_write_single_line_value(tmp_github_output: Path) -> None:
    write_output("pr_number", "42")
    assert tmp_github_output.read_text() == "pr_number=42\n"


def test_write_int_value_is_stringified(tmp_github_output: Path) -> None:
    write_output("iteration", 2)
    assert tmp_github_output.read_text() == "iteration=2\n"


def test_write_bool_value_is_lowercase(tmp_github_output: Path) -> None:
    write_output("qa_passed", True)
    assert tmp_github_output.read_text() == "qa_passed=true\n"


def test_write_multiline_uses_heredoc(tmp_github_output: Path) -> None:
    write_output("summary", "line one\nline two")
    text = tmp_github_output.read_text()
    assert "summary<<" in text
    assert "line one\nline two" in text
    # heredoc terminator on its own line
    delim = text.split("<<", 1)[1].split("\n", 1)[0]
    assert text.endswith(f"\n{delim}\n")


def test_write_multiple_outputs_appends(tmp_github_output: Path) -> None:
    write_output("a", "1")
    write_output("b", "2")
    assert tmp_github_output.read_text() == "a=1\nb=2\n"


def test_write_raises_when_github_output_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_OUTPUT"):
        write_output("k", "v")


def test_heredoc_delimiter_avoids_collision(tmp_github_output: Path) -> None:
    """If the value contains 'EOF' on its own line, the chosen delimiter must differ."""
    write_output("k", "before\nEOF\nafter")
    text = tmp_github_output.read_text()
    delim = text.split("<<", 1)[1].split("\n", 1)[0]
    assert delim != "EOF"
    # value preserved verbatim
    assert "before\nEOF\nafter" in text
