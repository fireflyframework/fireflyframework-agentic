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

"""``read_skill`` — the tool that makes progressive disclosure real.

The prompt section lists a skill's resources by path; this tool hands one over when the model
asks. It is a plain :class:`~fireflyframework_agentic.tools.base.BaseTool`: no approval, no
deferral, no side effects, reads only what the skills declared, and answers a wrong key or path
with a ``ModelRetry`` naming what does exist — the model corrects itself instead of the turn
failing on a typo.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic_ai import ModelRetry

from fireflyframework_agentic.skills.skill import Skill, validate_resource_path
from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec, ToolCallListener

DEFAULT_MAX_CHARS = 60_000


class ReadSkillTool(BaseTool):
    """See :func:`build_read_skill_tool`."""

    def __init__(
        self,
        skills: Iterable[Skill],
        *,
        name: str = "read_skill",
        max_chars: int | None = DEFAULT_MAX_CHARS,
        listeners: Sequence[ToolCallListener] = (),
    ) -> None:
        self._skills: dict[str, Skill] = {s.key: s for s in skills}
        self._max_chars = max_chars
        super().__init__(
            name,
            description=(
                "Read a resource (a reference document or a template) of one of your skills, by skill key and "
                "resource path, exactly as listed under that skill in your instructions. Call with an empty path "
                "to list a skill's resources. Read a resource on the turn you need it, not before."
            ),
            tags=("skills", "read-only"),
            parameters=[
                ParameterSpec(name="key", python_type=str, description="The skill key, e.g. x_local_gaap."),
                ParameterSpec(
                    name="path",
                    python_type=str,
                    description="The resource path as listed, e.g. checklist.md. Empty to list the skill's resources.",
                    required=False,
                    default="",
                ),
            ],
            listeners=listeners,
            # Opted in so a host's ledger listener receives the RunContext (and its
            # tool_call_id) for every read; ``_execute`` itself does not read it.
            takes_ctx=True,
        )

    @property
    def skills(self) -> dict[str, Skill]:
        return dict(self._skills)

    async def _execute(self, **kwargs: Any) -> Any:
        key = str(kwargs.get("key") or "")
        path = str(kwargs.get("path") or "")
        skill = self._skills.get(key)
        if skill is None:
            raise ModelRetry(
                f"There is no skill {key!r}. Your skills are: {', '.join(sorted(self._skills)) or 'none'}."
            )
        if not path:
            return self._listing(skill)
        try:
            normalised = validate_resource_path(path)
        except ValueError:
            normalised = ""
        resource = skill.resources.get(normalised)
        if resource is None or not resource.available:
            raise ModelRetry(
                f"Skill {key!r} has no resource {path!r}. Its resources are: {', '.join(sorted(skill.resources)) or 'none'}."
            )
        text = resource.read()
        if self._max_chars is not None and len(text) > self._max_chars:
            return (
                text[: self._max_chars]
                + f"\n\n[truncated: this resource is {len(text)} characters; the first {self._max_chars} are shown]"
            )
        return text

    @staticmethod
    def _listing(skill: Skill) -> str:
        if not skill.resources:
            return f"Skill {skill.key!r} ({skill.name}) has no resources."
        lines = [f"Resources of skill {skill.key!r} ({skill.name}):"]
        for path, resource in sorted(skill.resources.items()):
            label = f" — {resource.description}" if resource.description else ""
            lines.append(f"- {path} ({resource.kind}){label}")
        return "\n".join(lines)


def build_read_skill_tool(
    skills: Iterable[Skill],
    *,
    name: str = "read_skill",
    max_chars: int | None = DEFAULT_MAX_CHARS,
    listeners: Sequence[ToolCallListener] = (),
) -> ReadSkillTool:
    """The ``read_skill(key, path)`` tool over ``skills``.

    ``max_chars`` caps one answer (a resource is a document, and a document can be a book);
    ``listeners`` are :class:`~fireflyframework_agentic.tools.base.ToolCallListener` objects, so
    a host's ledger sees these reads like any other call.
    """
    return ReadSkillTool(skills, name=name, max_chars=max_chars, listeners=listeners)
