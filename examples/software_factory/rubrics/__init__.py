# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Agent rubrics — criteria each agent must satisfy (the loss to minimize)."""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def load_rubric(agent: str) -> str:
    """Return the rubric markdown for `agent` (e.g. 'deployer').

    Raises:
        FileNotFoundError: If no rubric exists for the given agent name.
    """
    path = _DIR / f"{agent}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no rubric found for agent '{agent}': {path}")
    return path.read_text(encoding="utf-8")
