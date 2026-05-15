# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _trace_from_messages,
)
from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    ThoughtStep,
)


def test_trace_translation_drops_system_and_user_parts():
    msgs = [
        ModelRequest(parts=[SystemPromptPart(content="sys")]),
        ModelRequest(parts=[UserPromptPart(content="hi")]),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert trace.steps == []
    assert trace.pattern_name == "reasoning_answerer"


def test_trace_translation_emits_action_and_observation():
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_call_id="t1",
                    tool_name="knowledge_search",
                    args={"query": "x", "top_k": 3},
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_call_id="t1",
                    tool_name="knowledge_search",
                    content="[{...}]",
                )
            ]
        ),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 2
    assert isinstance(trace.steps[0], ActionStep)
    assert trace.steps[0].tool_name == "knowledge_search"
    assert trace.steps[0].tool_args == {"query": "x", "top_k": 3}
    assert isinstance(trace.steps[1], ObservationStep)
    assert trace.steps[1].source == "knowledge_search"


def test_trace_translation_emits_thought_for_text_parts():
    msgs = [
        ModelResponse(parts=[TextPart(content="I should search first.")]),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 1
    assert isinstance(trace.steps[0], ThoughtStep)
    assert "search" in trace.steps[0].content


def test_trace_translation_truncates_long_observations():
    long = "x" * 5000
    msgs = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_call_id="t1",
                    tool_name="knowledge_search",
                    content=long,
                )
            ]
        ),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 1
    obs = trace.steps[0]
    assert isinstance(obs, ObservationStep)
    assert "more bytes" in obs.content
    assert len(obs.content) <= 2100  # cap + suffix
