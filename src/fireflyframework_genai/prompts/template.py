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

from fireflyframework_genai.exceptions import PromptError, PromptValidationError
from fireflyframework_genai.types import Metadata

# Shared Jinja2 environment with safe defaults
_jinja_env = Environment(loader=BaseLoader(), autoescape=False, keep_trailing_newline=True)

# Sentinel value to distinguish "no default" from ``default=None``.
_UNSET = object()


class PromptVariable(BaseModel):
    """Describes a single variable expected by a prompt template."""

    name: str
    description: str = ""
    required: bool = True
    default: Any = _UNSET


class PromptInfo(BaseModel):
    """Lightweight, serialisable summary of a registered prompt template."""

    name: str
    version: str
    variable_names: list[str] = []
    description: str = ""


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
        template_str: str,
        *,
        version: str = "1.0.0",
        description: str = "",
        variables: Sequence[PromptVariable] = (),
        metadata: Metadata | None = None,
    ) -> None:
        self._name = name
        self._template_str = template_str
        self._version = version
        self._description = description
        self._variables = list(variables)
        self._metadata: Metadata = metadata or {}

        try:
            self._compiled = _jinja_env.from_string(template_str)
        except TemplateSyntaxError as exc:
            raise PromptError(f"Invalid Jinja2 syntax in template '{name}': {exc}") from exc

    # -- Properties ----------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return self._description

    @property
    def template_str(self) -> str:
        return self._template_str

    @property
    def variables(self) -> list[PromptVariable]:
        return list(self._variables)

    @property
    def metadata(self) -> Metadata:
        return self._metadata

    # -- Rendering -----------------------------------------------------------

    def render(self, **kwargs: Any) -> str:
        """Render the template with the given variables.

        Applies defaults for missing optional variables, then delegates to
        Jinja2.

        Raises:
            PromptValidationError: If any required variable is missing.
        """
        self.validate_variables(kwargs)
        # Apply defaults for optional variables not provided
        merged = {}
        for var in self._variables:
            if var.name in kwargs:
                merged[var.name] = kwargs[var.name]
            elif var.default is not _UNSET:
                merged[var.name] = var.default
        # Include any extra kwargs not declared as variables
        for k, v in kwargs.items():
            if k not in merged:
                merged[k] = v
        return self._compiled.render(**merged)

    def validate_variables(self, kwargs: dict[str, Any]) -> None:
        """Raise :class:`PromptValidationError` if required variables are missing."""
        missing = [v.name for v in self._variables if v.required and v.name not in kwargs]
        if missing:
            raise PromptValidationError(f"Template '{self._name}' is missing required variables: {', '.join(missing)}")

    def estimate_tokens(self, **kwargs: Any) -> int:
        """Rough token estimate based on whitespace-split word count / 0.75.

        This is a heuristic approximation.  For accurate counts, integrate
        a tokeniser (e.g. tiktoken) at the application level.
        """
        rendered = self.render(**kwargs) if kwargs else self._template_str
        word_count = len(rendered.split())
        return int(word_count / 0.75)

    # -- Info ----------------------------------------------------------------

    def info(self) -> PromptInfo:
        return PromptInfo(
            name=self._name,
            version=self._version,
            variable_names=[v.name for v in self._variables],
            description=self._description,
        )

    def __repr__(self) -> str:
        return f"PromptTemplate(name={self._name!r}, version={self._version!r})"
