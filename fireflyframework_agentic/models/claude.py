# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Claude capability rules shared by the factory and its settings translation.

The Claude 4.7+ and Claude 5 families require these request rules:

* thinking is ``{"type": "adaptive"}`` and on by default; ``budget_tokens`` is a 400;
* ``temperature`` / ``top_p`` / ``top_k`` are a 400, thinking or not;
* effort is ``low`` … ``xhigh`` … ``max``.

Profiles are dictionaries in PydanticAI 2. Corrections are merged over the SDK's derived
profile, retaining thinking tags, native-tool capabilities, code-execution versions and all
other provider-specific fields.

The rules are pinned by ``tests/unit/models/test_factory.py``. Where the SDK already carries
them, merging the corrections leaves its values unchanged.
"""

from __future__ import annotations

import re
from typing import cast

from pydantic_ai.profiles import DEFAULT_PROFILE, ModelProfile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile, anthropic_model_profile

from fireflyframework_agentic.models.spec import ModelCapabilities, ThinkingStyle

#: Ids (prefixes) with adaptive thinking, every effort
#: level, budgets and sampling refused, native structured output.
CLAUDE_5_PREFIXES: tuple[str, ...] = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5")

#: Adaptive thinking (``{"type": "adaptive"}``) — Claude 4.6 and later.
ADAPTIVE_PREFIXES: tuple[str, ...] = (
    *CLAUDE_5_PREFIXES,
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
)

#: ``temperature`` / ``top_p`` / ``top_k`` refused outright, and ``budget_tokens`` refused —
#: Claude 4.7 and later. (4.6 still accepts sampling and deprecates budgets.)
SAMPLING_REFUSED_PREFIXES: tuple[str, ...] = (
    *CLAUDE_5_PREFIXES,
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
)

#: The ``xhigh`` effort level — Claude 4.7 and later.
XHIGH_PREFIXES: tuple[str, ...] = (
    *CLAUDE_5_PREFIXES,
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
)

#: The largest ``budget_tokens`` a budget-style Claude model accepts. Haiku 4.5 and the pre-4.6
#: family take a budget below ``max_tokens``; this ceiling keeps a generously configured worker
#: from failing every turn on a request the provider rejects whole.
DEFAULT_CLAUDE_BUDGET_CEILING = 32_000


#: A Bedrock cross-region inference profile prefixes the vendor with a geography:
#: ``us.``, ``eu.``, ``apac.``, ``global.``, ``us-gov.`` … — that is what a production account
#: calls, the bare ``anthropic.`` id being the single-region form. The version suffix
#: ``-v1`` / ``-v1:0`` is Bedrock's, not the model's.
_BEDROCK_GEO_PREFIX = re.compile(r"^[a-z]{2,6}(?:-gov)?\.(?=anthropic\.)")
_BEDROCK_VERSION_SUFFIX = re.compile(r"-v\d+(?::\d+)?$")


def _bare(model: str) -> str:
    """The Claude id without a Bedrock geo/vendor prefix and version, or a Vertex ``@version``.

    ``us.anthropic.claude-haiku-4-5-20251001-v1:0`` → ``claude-haiku-4-5-20251001``;
    ``anthropic.claude-opus-5`` → ``claude-opus-5``; ``claude-opus-4-5@20251101`` →
    ``claude-opus-4-5``. Only the ``anthropic.`` vendor is unwrapped: ``us.amazon.nova-pro``
    is not a Claude and must not become one by accident.
    """
    name = _BEDROCK_GEO_PREFIX.sub("", model.lower())
    if name.startswith("anthropic."):
        name = _BEDROCK_VERSION_SUFFIX.sub("", name[len("anthropic.") :])
    return name.split("@", 1)[0]


def bare_claude_id(model: str) -> str:
    """Public name of :func:`_bare`, for the price table and anything else keyed by the id."""
    return _bare(model)


def is_claude(model: str) -> bool:
    return _bare(model).startswith("claude")


def claude_thinking_style(model: str) -> ThinkingStyle:
    """``adaptive`` for 4.6 and later, ``budget`` for every earlier Claude, ``none`` otherwise."""
    name = _bare(model)
    if not name.startswith("claude"):
        return "none"
    if name.startswith(ADAPTIVE_PREFIXES):
        return "adaptive"
    return "budget"


def claude_capabilities(model: str) -> ModelCapabilities:
    """The :class:`ModelCapabilities` of a Claude id, from the tables above."""
    name = _bare(model)
    style = claude_thinking_style(name)
    if style == "none":
        return ModelCapabilities()
    return ModelCapabilities(
        thinking=True,
        thinking_style=style,
        max_thinking_budget_tokens=DEFAULT_CLAUDE_BUDGET_CEILING if style == "budget" else None,
        refuses_sampling=name.startswith(SAMPLING_REFUSED_PREFIXES),
    )


def claude_corrections(model: str) -> dict[str, object]:
    """The framework's Claude capability corrections for ``model``.

    Keyed by the ``AnthropicModelProfile`` field names; :func:`bedrock_claude_profile` maps
    the ones Bedrock's profile spells differently. Empty for a non-Claude id.
    """
    name = _bare(model)
    if not name.startswith("claude"):
        return {}
    corrections: dict[str, object] = {"supports_thinking": True}
    if name.startswith(ADAPTIVE_PREFIXES):
        corrections["anthropic_supports_adaptive_thinking"] = True
        corrections["anthropic_supports_effort"] = True
    if name.startswith(XHIGH_PREFIXES):
        corrections["anthropic_supports_xhigh_effort"] = True
    if name.startswith(SAMPLING_REFUSED_PREFIXES):
        corrections["anthropic_disallows_budget_thinking"] = True
        corrections["anthropic_disallows_sampling_settings"] = True
    if name.startswith(CLAUDE_5_PREFIXES):
        corrections["supports_json_schema_output"] = True
    return corrections


def claude_profile(model: str) -> AnthropicModelProfile:
    """The SDK's derived profile for ``model`` with the framework's corrections applied.

    For an id the SDK knows and gets right this is the SDK's own profile, replaced with the same
    values. For the Claude 5 family it is the SDK's profile with adaptive thinking, every effort
    level, refused budgets, refused sampling and native structured output switched on.
    """
    name = _bare(model)
    derived: ModelProfile | None = anthropic_model_profile(name)
    return cast("AnthropicModelProfile", {**(derived or DEFAULT_PROFILE), **claude_corrections(name)})


#: ``AnthropicModelProfile`` field → the ``BedrockModelProfile`` field that means the same thing.
#: Bedrock's ``_translate_thinking`` reads its own flags, not the Anthropic ones, so a correction
#: that stays under the Anthropic name is invisible there.
_BEDROCK_FIELD_FOR: dict[str, str] = {
    "anthropic_supports_adaptive_thinking": "bedrock_supports_adaptive_thinking",
    "anthropic_supports_effort": "bedrock_supports_effort",
}


def bedrock_claude_profile(model: str) -> ModelProfile:
    """The Bedrock provider's derived profile for a Claude id, with the corrections applied ON it.

    The SDK's Bedrock derivation (which already strips the geo prefix and the version suffix)
    is the base, preserving tool choice, prompt caching and its JSON-schema transformer. The
    Claude 5 corrections are mapped onto Bedrock's own flags. Anthropic-only correction keys
    without a Bedrock counterpart are left to the SDK's Bedrock profile; sampling is also
    filtered by the settings translation.
    """
    from pydantic_ai.providers.bedrock import BedrockProvider

    derived = BedrockProvider.model_profile(model)
    corrections: dict[str, object] = {}
    for field, value in claude_corrections(model).items():
        target = _BEDROCK_FIELD_FOR.get(field, field)
        if not field.startswith("anthropic_") or target != field:
            corrections[target] = value
    return cast("ModelProfile", {**(derived or DEFAULT_PROFILE), **corrections})
