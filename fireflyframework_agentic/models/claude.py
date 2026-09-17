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

"""What the framework knows about the Claude family that the pinned SDK's table does not.

pydantic-ai 1.107's ``anthropic_model_profile`` predates Claude Opus 5 and Claude Sonnet 5
(no 1.x release knows them; the profile table stops at the 4.8 line and Fable/Mythos 5). For
those ids it derives a profile that says no adaptive thinking, no effort, budgets allowed and
sampling allowed — and every one of those is the opposite of what the API does:

* thinking is ``{"type": "adaptive"}`` and on by default; ``budget_tokens`` is a 400;
* ``temperature`` / ``top_p`` / ``top_k`` are a 400, thinking or not;
* effort is ``low`` … ``xhigh`` … ``max``.

This module is the one place that table is corrected. The profile is MUTATED, NEVER
CONSTRUCTED: ``Model.profile`` falls back to the provider-derived profile only when the model
was given none, so passing a fresh ``AnthropicModelProfile(...)`` replaces the derived one
wholesale and silently drops ``thinking_tags``, the code-execution tool versions and every
flag the SDK did get right. ``dataclasses.replace`` keeps them and changes only what is wrong.

The rules come from the provider's documentation as of this release, and they are pinned by
``tests/unit/models/test_factory.py``; when a pydantic-ai release carries them, this module
becomes a no-op for the ids it covers, and that is the intended end of it.
"""

from __future__ import annotations

import dataclasses

from pydantic_ai.profiles import ModelProfile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile, anthropic_model_profile

from fireflyframework_agentic.models.spec import ModelCapabilities, ThinkingStyle

#: Ids (prefixes) whose profile the pinned SDK does not know: adaptive thinking, every effort
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


def _bare(model: str) -> str:
    """The Claude id without a Bedrock vendor prefix or a Vertex ``@version`` suffix."""
    name = model.lower()
    if name.startswith("anthropic."):
        name = name[len("anthropic.") :]
    return name.split("@", 1)[0]


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


def claude_profile(model: str) -> AnthropicModelProfile:
    """The SDK's derived profile for ``model`` with the framework's corrections applied.

    For an id the SDK knows and gets right this is the SDK's own profile, replaced with the same
    values. For the Claude 5 family it is the SDK's profile with adaptive thinking, every effort
    level, refused budgets, refused sampling and native structured output switched on.
    """
    name = _bare(model)
    derived: ModelProfile | None = anthropic_model_profile(name)
    base = AnthropicModelProfile.from_profile(derived) if derived is not None else AnthropicModelProfile()
    if not name.startswith("claude"):
        return base
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
    return dataclasses.replace(base, **corrections)  # type: ignore[arg-type]
