# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Write typed key/value pairs to the file pointed to by `$GITHUB_OUTPUT`.

GitHub Actions Docker actions communicate scalar outputs back to the workflow
by appending lines to this file. Multi-line values must use the heredoc form
documented at:
https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-an-output-parameter
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _heredoc_delimiter(text: str) -> str:
    """Return a delimiter that does not appear as a standalone line in `text`."""
    delim = "EOF"
    while f"\n{delim}\n" in f"\n{text}\n":
        delim = f"EOF_{secrets.token_hex(4)}"
    return delim


def write_output(key: str, value: Any) -> None:
    """Append `key=value` (or a heredoc block) to `$GITHUB_OUTPUT`.

    Raises:
        RuntimeError: If `GITHUB_OUTPUT` is not set in the environment.
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise RuntimeError("GITHUB_OUTPUT environment variable is not set")
    text = _format_scalar(value)
    out = Path(path)
    if "\n" in text:
        delim = _heredoc_delimiter(text)
        block = f"{key}<<{delim}\n{text}\n{delim}\n"
    else:
        block = f"{key}={text}\n"
    with out.open("a", encoding="utf-8") as fh:
        fh.write(block)
