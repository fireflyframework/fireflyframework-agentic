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

"""The ``## Skills`` section of a system prompt: bodies in, resources listed, never inlined."""

from __future__ import annotations

from collections.abc import Iterable

from fireflyframework_agentic.skills.skill import Skill


def render_skills_section(
    skills: Iterable[Skill],
    *,
    heading: str = "## Skills",
    read_tool_name: str = "read_skill",
) -> str:
    """One markdown section carrying every skill's name, when-to-use and rendered body.

    Each skill's resources are LISTED with the exact ``read_skill`` call that fetches them —
    the model learns what exists and what it costs nothing to know, and reads a document on the
    turn it needs it. Each skill is rendered with its bound config (and schema defaults), so a
    skill whose config is invalid raises here, at prompt-assembly time, rather than sending the
    model a body with holes in it. Returns ``""`` for no skills, so a caller can append it
    unconditionally.
    """
    skills = list(skills)
    if not skills:
        return ""
    parts: list[str] = [heading, ""]
    for skill in skills:
        parts.append(f"### {skill.name}")
        parts.append(f"Skill key: `{skill.key}` (version {skill.version})")
        if skill.when_to_use:
            parts.append(f"When to use: {skill.when_to_use}")
        parts.append("")
        parts.append(skill.render())
        if skill.resources:
            parts.append("")
            parts.append(
                f'Resources for this skill (read one with `{read_tool_name}(key="{skill.key}", path="<path>")`; '
                "read only what the step you are on needs):"
            )
            for path, resource in sorted(skill.resources.items()):
                label = f" — {resource.description}" if resource.description else ""
                parts.append(f'- `{read_tool_name}(key="{skill.key}", path="{path}")` ({resource.kind}){label}')
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"
