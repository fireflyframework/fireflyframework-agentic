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

"""Jinja2-based prompt template engine.

:class:`PromptTemplate` wraps a Jinja2 template string with metadata,
variable validation, and a rough token estimator.  Templates are the
atomic unit of the Firefly prompt system.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateSyntaxError
from pydantic import BaseModel

from fireflyframework_agentic.exceptions import PromptError, PromptValidationError
from fireflyframework_agentic.types import Metadata

# Shared Jinja2 environment with safe defaults
_jinja_env = Environment(loader=BaseLoader(), autoescape=False, keep_trailing_newline=True)


class PromptInfo(BaseModel):
    """Lightweight, serialisable summary of a registered prompt template."""

    name: str
    version: str
    variable_names: list[str] = []
    description: str = ""


class Prompt(BaseModel):
    system: str
    user: str

    def estimate_tokens(self) -> int:
        """Rough token estimate based on whitespace-split word count / 0.75.

        This is a heuristic approximation.  For accurate counts, integrate
        a tokeniser (e.g. tiktoken) at the application level.
        """
        system_word_count = len(self.system.split())
        user_word_count = len(self.user.split())
        return int((system_word_count + user_word_count) / 0.75)


class PromptTemplate:
    """A named, versioned prompt template backed by Jinja2.

    Parameters:
        name: Unique template name.
        template_str: Jinja2 template source.
        version: Semantic version string.
        description: Human-readable description.
        variables: Declared variables (used for validation and docs).
        metadata: Arbitrary key-value metadata.
    """

    def __init__(
        self,
        name: str,
        system_template: str,
        user_template: str,
        *,
        version: str = "1.0.0",
        description: str = "",
        required_variables: list[str] | None = None,
        metadata: Metadata | None = None,
    ) -> None:
        self.name = name
        self.system_template = system_template
        self.user_template = user_template
        self.version = version
        self.description = description
        self.required_variables = required_variables or []
        self.metadata = metadata
        self._compiled = {}

        try:
            if self.system_template:
                self._compiled["system"] = _jinja_env.from_string(self.system_template)

            if self.user_template:
                self._compiled["user"] = _jinja_env.from_string(self.user_template)

        except TemplateSyntaxError as exc:
            raise PromptError(f"Invalid Jinja2 syntax in template '{name}': {exc}") from exc

    # -- Rendering -----------------------------------------------------------

    def render(self, **kwargs: Any) -> Prompt:
        """Render the template with the given variables.

        Applies defaults for missing optional variables, then delegates to
        Jinja2.

        Raises:
            PromptValidationError: If any required variable is missing.
        """
        self.validate_variables(kwargs)
        # Apply defaults for optional variables not provided

        return Prompt(
            system=self._compiled["system"].render(**kwargs) if "system" in self._compiled else "",
            user=self._compiled["user"].render(**kwargs) if "user" in self._compiled else "",
        )

    def validate_variables(self, kwargs: dict[str, Any]) -> None:
        """Raise :class:`PromptValidationError` if required variables are missing."""
        required = set(self.required_variables)
        provided = set(kwargs.keys())
        missing = required - provided
        if missing:
            raise PromptValidationError(f"Template '{self.name}' is missing required variables: {', '.join(missing)}")

    # -- Info ----------------------------------------------------------------

    def info(self) -> PromptInfo:
        return PromptInfo(
            name=self.name,
            version=self.version,
            variable_names=list(self.required_variables),
            description=self.description,
        )

    def __repr__(self) -> str:
        return f"PromptTemplate(name={self.name!r}, version={self.version!r})"
