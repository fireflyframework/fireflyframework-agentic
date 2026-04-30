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

"""Prompt composition strategies: sequential, conditional, and merge.

Composers combine multiple :class:`PromptTemplate` instances into a single
rendered string using different strategies.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fireflyframework_agentic.prompts.template import Prompt, PromptTemplate


class SequentialComposer:
    """Render templates in order and join with a separator.

    Parameters:
        templates: Ordered sequence of templates to render.
        separator: String inserted between rendered outputs.
    """

    def __init__(
        self,
        templates: Sequence[PromptTemplate],
        *,
        separator: str = "\n\n",
    ) -> None:
        self._templates = list(templates)
        self._separator = separator

    def render(self, **kwargs: Any) -> Prompt:
        """Render each template and join with the separator."""
        system_parts = [t.render(**kwargs).system for t in self._templates]
        user_parts = [t.render(**kwargs).user for t in self._templates]
        return Prompt(
            system=self._separator.join(system_parts),
            user=self._separator.join(user_parts),
        )


class ConditionalComposer:
    """Select a template based on a condition function.

    Parameters:
        condition_fn: Callable that receives kwargs and returns a template
            name from *template_map*.
        template_map: Mapping of condition keys to templates.
    """

    def __init__(
        self,
        condition_fn: Callable[..., str],
        template_map: dict[str, PromptTemplate],
    ) -> None:
        self._condition_fn = condition_fn
        self._template_map = dict(template_map)

    def render(self, **kwargs: Any) -> Prompt:
        """Evaluate condition, select the template, and render it."""
        key = self._condition_fn(**kwargs)
        if key not in self._template_map:
            raise KeyError(f"Condition returned unknown key '{key}'")
        return Prompt(
            system=self._template_map[key].render(**kwargs).system,
            user=self._template_map[key].render(**kwargs).user,
        )


class MergeComposer:
    """Render templates and merge their outputs using a custom function.

    Parameters:
        templates: Templates to render.
        merge_fn: Callable that receives a list of rendered strings and
            returns the merged result.
    """

    def __init__(
        self,
        templates: Sequence[PromptTemplate],
        merge_fn: Callable[[list[str]], str],
    ) -> None:
        self._templates = list(templates)
        self._merge_fn = merge_fn

    def render(self, **kwargs: Any) -> Prompt:
        """Render all templates and merge the results."""
        system_parts = [t.render(**kwargs).system for t in self._templates]
        user_parts = [t.render(**kwargs).user for t in self._templates]
        return Prompt(
            system=self._merge_fn(system_parts),
            user=self._merge_fn(user_parts),
        )
