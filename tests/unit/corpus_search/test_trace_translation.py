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


def test_trace_translation_filters_final_result_plumbing():
    """pydantic-ai's implicit output tool (default name 'final_result')
    must not appear in the trace — the Answer itself carries that content,
    and surfacing it would confuse trace replay (no closure to call).
    """
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_call_id="final0",
                    tool_name="final_result",
                    args={"text": "...", "citations": []},
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_call_id="final0",
                    tool_name="final_result",
                    content="ok",
                )
            ]
        ),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert trace.steps == []


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


def test_trace_translation_preserves_args_when_serialised_as_json_string():
    """Regression for the OpenAI-provider case.

    pydantic-ai's ToolCallPart.args is ``str | dict | None``. Anthropic
    delivers a dict; OpenAI delivers a JSON string. Reading ``.args``
    directly with an ``isinstance(..., dict)`` gate silently drops args
    for OpenAI-served runs and breaks reproducibility — every replayed
    tool call would receive ``{}``.

    The fix is to use ``args_as_dict()`` (the canonical accessor) so the
    same trace shape comes out regardless of provider.
    """
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_call_id="t1",
                    tool_name="knowledge_search",
                    # The OpenAI shape: args is a JSON string, NOT a dict.
                    args='{"query": "hello", "top_k": 3}',
                )
            ]
        ),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 1
    assert isinstance(trace.steps[0], ActionStep)
    assert trace.steps[0].tool_name == "knowledge_search"
    # The reproducibility-critical assertion: args round-trip to dict losslessly.
    assert trace.steps[0].tool_args == {"query": "hello", "top_k": 3}, (
        "ActionStep.tool_args must be a parsed dict regardless of whether the "
        "provider delivered the args as a string or a dict — otherwise "
        "test_trace_is_replayable cannot reproduce OpenAI-served traces."
    )


def test_trace_translation_handles_malformed_args_string_gracefully():
    """If args is a malformed JSON string, the trace is still emitted —
    pydantic-ai's ``args_as_dict()`` returns ``{"INVALID_JSON": <raw>}``
    rather than raising, so the operator gets the raw text preserved for
    debugging. The step is non-replayable but the trace stays well-formed.
    """
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_call_id="t1",
                    tool_name="knowledge_search",
                    args='{"q": malformed',  # not valid JSON
                )
            ]
        ),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 1
    step = trace.steps[0]
    assert isinstance(step, ActionStep)
    assert step.tool_name == "knowledge_search"
    # Raw text preserved; the dict is non-empty but contains the marker key.
    assert "INVALID_JSON" in step.tool_args or step.tool_args == {}
    # Either way, the trace is JSON-serialisable for downstream consumers.
    import json

    json.dumps(step.tool_args)  # must not raise
