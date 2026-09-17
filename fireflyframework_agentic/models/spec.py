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

"""The description a :class:`~fireflyframework_agentic.models.factory.ModelFactory` builds from.

A host that keeps its model choice as data — a catalogue row, a tenant's account, a worker's
parameter profile — describes the model in these four parts and hands them to the factory. The
description carries no decision the factory has to make: which SDK class, which id, which
provider arguments, which measured profile corrections and which capabilities are all stated,
or derived from the model id by a table the framework owns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

ThinkingStyle = Literal["none", "budget", "effort", "adaptive"]
"""How a model is asked to think.

* ``none`` — the model has no thinking mode; a thinking budget in the settings is dropped.
* ``budget`` — ``{"type": "enabled", "budget_tokens": N}`` (Claude Haiku 4.5 and the pre-4.6
  family); extended thinking refuses the sampling knobs.
* ``effort`` — a label (``openai_reasoning_effort``): the OpenAI reasoning models.
* ``adaptive`` — ``{"type": "adaptive"}`` plus an effort level (Claude 4.6 and later); the
  4.7+ family and the Claude 5 family also refuse the sampling knobs outright.
"""


@runtime_checkable
class CredentialResolver(Protocol):
    """Turns a credential reference into the secret itself.

    A protocol, not a class, because the production implementation calls a vault over HTTP and
    the test one returns a fixture; neither the factory nor anything above it should know which.
    """

    async def resolve(self, reference: str, version: int) -> str:
        """Return the secret ``reference`` names at ``version``."""
        ...


@dataclass(frozen=True)
class Credential:
    """How the model authenticates.

    Three shapes, built with the class methods: a secret carried inline (:meth:`api_key`), a
    reference the factory redeems through a :class:`CredentialResolver` (:meth:`reference`) —
    the shape for a process that must never hold a key — and no credential at all
    (:meth:`none`) for a local model or a key the SDK reads from its own environment.
    """

    kind: Literal["api_key", "reference", "none"]
    secret: str | None = None
    reference_id: str | None = None
    version: int = 1

    @classmethod
    def api_key(cls, secret: str) -> Credential:
        return cls(kind="api_key", secret=secret)

    @classmethod
    def reference(cls, reference_id: str, version: int = 1) -> Credential:
        return cls(kind="reference", reference_id=reference_id, version=version)

    @classmethod
    def none(cls) -> Credential:
        return cls(kind="none")


@dataclass(frozen=True)
class ModelCapabilities:
    """What a model can be asked for, so a setting it cannot honour is dropped rather than sent.

    Asking Haiku for an effort level, or Sonnet 5 for ``top_k``, is not an error at the provider
    in every case — sometimes it is a 400, sometimes it is silently ignored — and the second is
    worse, because a console would show a knob that never applied. Stating the capabilities lets
    :func:`~fireflyframework_agentic.models.factory.model_settings_for` send only what the model
    takes. Omit them on the spec and :func:`~fireflyframework_agentic.models.factory.capabilities_for`
    derives them from the model id.
    """

    thinking: bool = False
    thinking_style: ThinkingStyle = "none"
    max_thinking_budget_tokens: int | None = None
    #: The model refuses ``temperature`` / ``top_p`` / ``top_k`` whether or not thinking is
    #: requested (Claude 4.7+, Claude 5).
    refuses_sampling: bool = False
    service_tier: bool = False


def _frozen_mapping(value: Any) -> Any:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class ModelSpec:
    """A model, described as data.

    Parameters:
        provider: The provider key — ``anthropic``, ``openai``, ``azure``, ``bedrock``,
            ``google-vertex``, ``google``, ``mistral``, or any OpenAI-compatible endpoint
            (``ollama``, ``openrouter``, ``deepseek``, …) with a ``base_url``.
        model: The provider's model id, exactly as the provider names it.
        credential: See :class:`Credential`.
        settings: The parameter profile in the console vocabulary (``maxTokens``,
            ``thinkingBudgetTokens``, ``topP`` …) or pydantic-ai's (``max_tokens`` …); both
            spellings are read.
        capabilities: What the model takes; derived from the id when omitted.
        model_class: The pydantic-ai class to build, when the provider alone does not decide
            it (``OpenAIResponsesModel`` beside ``OpenAIChatModel``).
        profile_overrides: Measured corrections to the SDK's derived
            :class:`~pydantic_ai.profiles.ModelProfile`, applied with ``dataclasses.replace``.
        base_url, api_version, region, project: Provider arguments where they apply
            (an OpenAI-compatible endpoint, Azure, Bedrock, Vertex).
    """

    provider: str
    model: str
    credential: Credential = field(default_factory=Credential.none)
    settings: Any = field(default_factory=dict)
    capabilities: ModelCapabilities | None = None
    model_class: str | None = None
    profile_overrides: Any = field(default_factory=dict)
    base_url: str | None = None
    api_version: str | None = None
    region: str | None = None
    project: str | None = None

    def __post_init__(self) -> None:
        # Frozen all the way down: a spec is a value, and a host may cache models by it.
        object.__setattr__(self, "settings", _frozen_mapping(self.settings))
        object.__setattr__(self, "profile_overrides", _frozen_mapping(self.profile_overrides))
