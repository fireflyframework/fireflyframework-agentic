# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests that every agent has a rubric and that rubrics are non-empty."""

from __future__ import annotations

import pytest

from software_factory.rubrics import load_rubric

AGENTS = ["po", "architect", "codegen", "guardian", "builder", "deployer", "qa"]


@pytest.mark.parametrize("agent", AGENTS)
def test_rubric_exists_and_nonempty(agent: str) -> None:
    rubric = load_rubric(agent)
    assert rubric.strip(), f"rubric for '{agent}' is empty"


@pytest.mark.parametrize("agent", AGENTS)
def test_rubric_has_hard_criteria_section(agent: str) -> None:
    rubric = load_rubric(agent)
    assert "Hard criteria" in rubric, f"rubric for '{agent}' has no 'Hard criteria' section"


def test_missing_rubric_raises() -> None:
    with pytest.raises(FileNotFoundError, match="no rubric found"):
        load_rubric("nonexistent_agent")
