"""Evaluation keeps endpoint choice distinct from provider identity."""

import pytest

from fireflyframework_agentic.evaluation.judge import EvalContext, JudgeClient, _make_ragas_llm, same_provider


@pytest.mark.parametrize("alias", ["openai-chat", "openai-responses"])
def test_judge_recognizes_same_provider_across_api_selectors(alias):
    assert same_provider("openai:gpt-4o", f"{alias}:gpt-6-sol")


@pytest.mark.parametrize(
    ("model", "responses", "temperature"),
    [
        ("openai:gpt-4o", False, 0.0),
        ("openai-chat:gpt-6-sol", False, None),
        ("openai-responses:gpt-6-astra", True, None),
    ],
)
def test_ragas_openai_adapter_selects_api_without_unsupported_sampling(monkeypatch, model, responses, temperature):
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    llm = _make_ragas_llm(EvalContext(client=JudgeClient(model)))
    assert llm.use_responses_api is responses
    assert llm.temperature == temperature


@pytest.mark.parametrize("alias,responses", [("azure-chat", False), ("azure-responses", True)])
def test_ragas_azure_adapter_preserves_selected_api(monkeypatch, alias, responses):
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("OPENAI_API_VERSION", "2025-04-01-preview")
    llm = _make_ragas_llm(EvalContext(client=JudgeClient(f"{alias}:deployment")))
    assert llm.use_responses_api is responses
    assert llm.temperature is None


def test_ragas_anthropic_adapter_omits_unsupported_sampling(monkeypatch):
    pytest.importorskip("langchain_anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    llm = _make_ragas_llm(EvalContext(client=JudgeClient("anthropic:claude-sonnet-5")))
    assert llm.temperature is None
