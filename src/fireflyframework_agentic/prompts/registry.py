# Copyright 2026 Firefly Software Solutions Inc
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

"""Global prompt template registry with version tracking.

Templates are keyed by ``(name, version)`` pairs.  When retrieving a
template without specifying a version, the registry returns the latest
registered version.
"""

from __future__ import annotations

import logging

from fireflyframework_agentic.exceptions import PromptNotFoundError
from fireflyframework_agentic.prompts.template import PromptInfo, PromptTemplate

PROMPT_TEMPLATE_REGISTRY: PromptRegistry | None = None


logger = logging.getLogger(__name__)


class PromptRegistry:
    """Central registry for prompt templates.

    Templates are stored under ``(name, version)`` pairs.  The *latest*
    pointer per name is updated on every :meth:`register` call.
    """

    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], PromptTemplate] = {}
        self._latest: dict[str, str] = {}  # name -> latest version

    def register(self, template: PromptTemplate) -> None:
        """Register *template* under its name and version."""
        key = (template.name, template.version)
        self._templates[key] = template
        self._latest[template.name] = template.version
        logger.debug("Registered prompt '%s' v%s", template.name, template.version)

    def get(self, name: str, version: str | None = None) -> PromptTemplate:
        """Return the template registered under *name*.

        If *version* is ``None``, the latest registered version is returned.

        Raises:
            PromptNotFoundError: If no matching template exists.
        """
        resolved_version = version or self._latest.get(name)
        if resolved_version is None:
            raise PromptNotFoundError(f"No prompt template registered with name '{name}'")
        key = (name, resolved_version)
        if key not in self._templates:
            raise PromptNotFoundError(f"No prompt template '{name}' with version '{resolved_version}'")
        return self._templates[key]

    def has(self, name: str) -> bool:
        """Return *True* if at least one version of *name* is registered."""
        return name in self._latest

    def list_templates(self) -> list[PromptInfo]:
        """Return a :class:`PromptInfo` summary for every registered template."""
        return [t.info() for t in self._templates.values()]

    def clear(self) -> None:
        """Remove all registered templates."""
        self._templates.clear()
        self._latest.clear()

    def __len__(self) -> int:
        return len(self._templates)

    def __contains__(self, name: str) -> bool:
        return name in self._latest


def get_prompt_registry() -> PromptRegistry:
    global PROMPT_TEMPLATE_REGISTRY
    if not PROMPT_TEMPLATE_REGISTRY:
        PROMPT_TEMPLATE_REGISTRY = PromptRegistry()
    return PROMPT_TEMPLATE_REGISTRY


prompt_registry: PromptRegistry = get_prompt_registry()
