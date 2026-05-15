# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit-level guards on the contradiction-handling rule.

Both the fast-path ``AnswerAgent._INSTRUCTIONS`` and the reasoning-path
``ReasoningAnswerAgent._SYSTEM`` must explicitly tell the model to surface
conflicting evidence rather than silently pick one source. The real test
that the model actually follows the rule lives in the Tier B
``test_corpus_query_contradiction_real_llm.py`` suite — these asserts
are belt-and-braces so a future drive-by edit doesn't drop the rule on
the floor.
"""

import re


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_fast_path_instructions_carry_contradiction_rule():
    from fireflyframework_agentic.rag.retrieval.answerer import _INSTRUCTIONS

    flat = _flat(_INSTRUCTIONS)
    assert "contradict" in flat, "fast-path prompt must mention contradiction"
    # Strong directive: MUST surface, do not pick silently.
    assert "MUST surface" in flat
    assert "without a basis" in flat


def test_reasoning_path_system_prompt_carries_contradiction_rule():
    from fireflyframework_agentic.rag.retrieval.reasoning_answerer import _SYSTEM

    flat = _flat(_SYSTEM)
    assert "contradict" in flat, "reasoning prompt must mention contradiction"
    assert "MUST surface" in flat
    assert "without a basis" in flat
