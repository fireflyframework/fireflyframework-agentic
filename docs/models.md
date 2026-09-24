---
title: Models
description: Describe a model as data, build it with ModelFactory, and let the framework apply each provider's thinking and sampling rules.
---

# Models

`fireflyframework_agentic.models` builds a pydantic-ai `Model` from a **description** — provider,
model id, credential, settings — and translates a parameter profile into the `ModelSettings` a
provider will actually accept. A host that keeps its model choice in a catalogue, a tenant account
or a worker profile hands the framework the row; the framework knows the SDK classes, the provider
arguments, and the rules that otherwise surface as a 400 on the first real turn.

## Describe

```python
from fireflyframework_agentic.models import Credential, ModelSpec

spec = ModelSpec(
    provider="anthropic",
    model="claude-sonnet-5",
    credential=Credential.reference("llm-account-42", version=3),   # or Credential.api_key("...")
    settings={"maxTokens": 4096, "thinkingBudgetTokens": 8192, "temperature": 0.2},
)
```

| Field | Meaning |
|---|---|
| `provider` | `anthropic`, `openai`, `azure`, `bedrock`, `google`, `google-vertex`, `mistral`, or any OpenAI-compatible endpoint (`ollama`, `openrouter`, `deepseek`, …) with a `base_url`. |
| `model` | The provider's id, as the provider names it (`anthropic.claude-opus-5` and the cross-region `us.anthropic.claude-opus-5-v1:0` on Bedrock, `claude-opus-5@…` on Vertex are recognised). |
| `credential` | `Credential.api_key(secret)`, `Credential.reference(id, version)` redeemed through a `CredentialResolver`, or `Credential.none()`. |
| `settings` | The parameter profile, in the console vocabulary (`maxTokens`, `thinkingBudgetTokens`, `topP`, `effort`, `serviceTier`) or pydantic-ai's (`max_tokens`, …). |
| `capabilities` | Optional `ModelCapabilities`; derived from the model id when omitted. |
| `model_class` | When the provider alone does not decide it: `OpenAIResponsesModel` beside the default `OpenAIChatModel`. |
| `profile_overrides` | Measured corrections to the SDK's derived `ModelProfile`, applied with `dataclasses.replace`. |
| `base_url`, `api_version`, `region`, `project` | Provider arguments where they apply. |

Specs are frozen values: a host may cache built models by them.

## Build

```python
from fireflyframework_agentic.models import ModelFactory

class Vault:
    async def resolve(self, reference: str, version: int) -> str: ...

factory = ModelFactory(credentials=Vault())
model = await factory.build(spec)            # a pydantic_ai Model
settings = factory.settings_for(spec)        # ModelSettings for FireflyAgent(model_settings=...)
```

A spec that cannot be followed — an unknown class, a reference with no resolver, a Bedrock
credential of the wrong shape, Azure without an API version — raises `ModelBuildError` naming
what is wrong. It is a configuration error, so the message says what would fix it and nothing
retries.

## What the framework knows about Claude

pydantic-ai 1.107's Anthropic profile table predates Claude Opus 5 and Claude Sonnet 5, and no
1.x release carries them. The factory corrects the derived profile for those ids
(`fireflyframework_agentic.models.claude`) — always with `dataclasses.replace`, never by
constructing a profile, so the SDK's own `thinking_tags` and tool versions survive:

| Family | Thinking | `budget_tokens` | `temperature` / `top_p` / `top_k` | Effort levels |
|---|---|---|---|---|
| Opus 5, Sonnet 5 | `{"type": "adaptive"}` (on by default) | refused (400) | refused (400) | `low` … `xhigh`, `max` |
| Opus 4.7 / 4.8 | adaptive | refused | refused | `low` … `xhigh`, `max` |
| Opus 4.6 / Sonnet 4.6 | adaptive | deprecated | allowed | `low` … `max` |
| Haiku 4.5 and earlier | `{"type": "enabled", "budget_tokens": N}` | required for thinking | allowed, except with thinking on | — |

`model_settings_for` applies those rules to a profile:

```python
>>> model_settings_for(ModelSpec("anthropic", "claude-sonnet-5", settings={"temperature": 0.2, "thinkingBudgetTokens": 8192}))
{'anthropic_thinking': {'type': 'adaptive'}, 'anthropic_effort': 'medium'}
>>> model_settings_for(ModelSpec("anthropic", "claude-haiku-4-5", settings={"temperature": 0.2, "thinkingBudgetTokens": 64000}))
{'anthropic_thinking': {'type': 'enabled', 'budget_tokens': 32000}}
>>> model_settings_for(ModelSpec("openai", "gpt-5", settings={"thinkingBudgetTokens": 8192}))
{'openai_reasoning_effort': 'medium'}
```

- A model that refuses the sampling knobs loses them whether or not a budget was set — thinking is
  on by default on the Claude 5 family, so the model turns the rule on, not the budget.
- A budget-style thinking turn also loses them (Anthropic: "`temperature` may only be set to 1
  when thinking is enabled") and the budget is clamped to the model's ceiling.
- A budget on an adaptive model is folded onto an effort level through `EFFORT_BUDGETS`
  (`minimal` 1024, `low` 4096, `medium` 8192, `high` 16384, `xhigh` 32768); an explicit
  `effort` wins. An effort-style model takes the label. A model without thinking drops the
  budget rather than sending a key the provider would reject or ignore.
- `serviceTier` is passed only for a model whose capabilities declare it.

### Claude on Bedrock

Bedrock names the same Claude three ways — `anthropic.claude-opus-5` (single region),
`us.anthropic.claude-opus-5` / `global.anthropic.claude-sonnet-5` / `eu.` / `apac.` /
`us-gov.` (a cross-region inference profile, what a production account calls) and the dated
`us.anthropic.claude-haiku-4-5-20251001-v1:0` — and every one is recognised as that Claude.
`BedrockConverseModel` reads thinking from `bedrock_additional_model_requests_fields`, never
from `anthropic_thinking` / `anthropic_effort`, so for `provider="bedrock"` the translation
writes the Anthropic wire shape into that key:

```python
>>> model_settings_for(ModelSpec("bedrock", "us.anthropic.claude-opus-5", settings={"temperature": 0.2, "effort": "xhigh"}))
{'bedrock_additional_model_requests_fields': {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'xhigh'}}}
>>> model_settings_for(ModelSpec("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0", settings={"thinkingBudgetTokens": 2048}))
{'bedrock_additional_model_requests_fields': {'thinking': {'type': 'enabled', 'budget_tokens': 2048}}}
```

The built model's profile is the Bedrock provider's own (tool choice, prompt caching, the
Bedrock JSON-schema transformer all kept) with the Claude 5 corrections mapped onto Bedrock's
flags (`bedrock_supports_adaptive_thinking`, `bedrock_supports_effort`), not an Anthropic
profile put in its place.

## Cost

`genai-prices` does not price the Claude 5 ids yet, so the default resolver chain carries a
framework price table (`framework_price_table_cost`, before `genai_prices_cost`) with the
Anthropic first-party rates for `claude-opus-5`, `claude-sonnet-5` and `claude-fable-5`, cache
writes at 1.25× and cache reads at 0.10× input. A row is removed the day genai-prices carries it.
