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

"""Skills: units of know-how an agent carries, with progressive disclosure.

* :class:`Skill` — frontmatter fields, a markdown body rendered over a config, resources.
* :func:`parse_skill` / :func:`load_skill` — from ``SKILL.md`` text or a directory.
* :func:`render_skills_section` — the ``## Skills`` part of a system prompt.
* :func:`build_read_skill_tool` — the ``read_skill(key, path)`` tool that fetches a resource.
"""

from fireflyframework_agentic.skills.markdown import load_skill, parse_skill, split_frontmatter
from fireflyframework_agentic.skills.prompt import render_skills_section
from fireflyframework_agentic.skills.skill import (
    KEY_PATTERN,
    Skill,
    SkillConfigError,
    SkillParseError,
    SkillRequirements,
    SkillResource,
    validate_resource_path,
)
from fireflyframework_agentic.skills.tool import ReadSkillTool, build_read_skill_tool

__all__ = [
    "KEY_PATTERN",
    "ReadSkillTool",
    "Skill",
    "SkillConfigError",
    "SkillParseError",
    "SkillRequirements",
    "SkillResource",
    "build_read_skill_tool",
    "load_skill",
    "parse_skill",
    "render_skills_section",
    "split_frontmatter",
    "validate_resource_path",
]
