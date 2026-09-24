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

"""Models as data: describe a model, build it, translate its settings.

* :class:`ModelSpec` — provider, model id, :class:`Credential`, settings, capabilities.
* :class:`ModelFactory` — a pydantic-ai ``Model`` from a spec, credential resolved by reference.
* :func:`model_settings_for` — the spec's parameter profile as ``ModelSettings`` keys, with the
  provider's thinking and sampling rules applied.
* :func:`claude_profile` / :func:`capabilities_for` — what the framework knows about the Claude
  family that the pinned pydantic-ai profile table does not.
"""

from fireflyframework_agentic.models.claude import (
    ADAPTIVE_PREFIXES,
    CLAUDE_5_PREFIXES,
    SAMPLING_REFUSED_PREFIXES,
    bare_claude_id,
    bedrock_claude_profile,
    claude_capabilities,
    claude_corrections,
    claude_profile,
    claude_thinking_style,
    is_claude,
)
from fireflyframework_agentic.models.factory import (
    BUILDERS,
    DEFAULT_CLASS_BY_PROVIDER,
    EFFORT_BUDGETS,
    ModelBuildError,
    ModelFactory,
    anthropic_effort_for,
    capabilities_for,
    effort_for,
    model_settings_for,
    profile_for,
)
from fireflyframework_agentic.models.spec import (
    Credential,
    CredentialResolver,
    ModelCapabilities,
    ModelSpec,
    ThinkingStyle,
)

__all__ = [
    "ADAPTIVE_PREFIXES",
    "BUILDERS",
    "CLAUDE_5_PREFIXES",
    "DEFAULT_CLASS_BY_PROVIDER",
    "EFFORT_BUDGETS",
    "SAMPLING_REFUSED_PREFIXES",
    "Credential",
    "CredentialResolver",
    "ModelBuildError",
    "ModelCapabilities",
    "ModelFactory",
    "ModelSpec",
    "ThinkingStyle",
    "anthropic_effort_for",
    "bare_claude_id",
    "bedrock_claude_profile",
    "capabilities_for",
    "claude_capabilities",
    "claude_corrections",
    "claude_profile",
    "claude_thinking_style",
    "effort_for",
    "is_claude",
    "model_settings_for",
    "profile_for",
]
