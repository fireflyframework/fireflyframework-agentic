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

"""``SKILL.md`` in, :class:`~fireflyframework_agentic.skills.skill.Skill` out.

The file is YAML frontmatter between ``---`` fences and a markdown body — the Agent Skills
layout, so a skill authored for one host reads in another. :func:`parse_skill` reads the text;
:func:`load_skill` reads a directory (``SKILL.md`` plus the resources the frontmatter declares,
loaded lazily and only those: the directory is not a file share).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from fireflyframework_agentic.skills.skill import (
    Skill,
    SkillParseError,
    SkillRequirements,
    SkillResource,
    validate_resource_path,
)

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)

#: The frontmatter keys the framework reads. Anything else is kept under ``metadata`` — a host
#: may carry its own (an owner id, a status) without the parser refusing the file.
KNOWN_KEYS = frozenset(
    {"key", "name", "description", "when_to_use", "version", "examples", "parameters_schema", "requires", "resources"}
)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """``(frontmatter, body)`` from a SKILL.md text."""
    match = _FRONTMATTER.match(text.lstrip("﻿"))
    if match is None:
        raise SkillParseError("a skill begins with YAML frontmatter between '---' fences")
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SkillParseError("frontmatter must be a mapping")
    return dict(loaded), match.group(2).strip()


def _resources_from(raw: Any) -> dict[str, SkillResource]:
    """The resource index: ``path: description`` or ``path: {kind, description, media_type}``."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise SkillParseError("resources must be a mapping of path -> description or path -> {kind, description}")
    index: dict[str, SkillResource] = {}
    for path, spec in raw.items():
        normalised = validate_resource_path(str(path))
        if isinstance(spec, str) or spec is None:
            index[normalised] = SkillResource(path=normalised, description=spec or "")
            continue
        if not isinstance(spec, Mapping):
            raise SkillParseError(f"resource {path!r} must be a description or a mapping")
        kind = str(spec.get("kind", "reference"))
        if kind not in ("reference", "template", "script"):
            raise SkillParseError(f"resource {path!r} has unknown kind {kind!r}")
        index[normalised] = SkillResource(
            path=normalised,
            kind=kind,  # type: ignore[arg-type]
            description=str(spec.get("description", "") or ""),
            media_type=str(spec.get("media_type", "text/markdown") or "text/markdown"),
        )
    return index


def parse_skill(text: str, *, key: str | None = None) -> Skill:
    """A :class:`Skill` from SKILL.md text. ``key`` overrides the frontmatter's ``key``."""
    front, body = split_frontmatter(text)
    resolved_key = key if key is not None else front.get("key")
    if not isinstance(resolved_key, str) or not resolved_key:
        raise SkillParseError("a skill needs a key: pass key= or set 'key' in the frontmatter")
    examples_raw = front.get("examples") or ()
    if isinstance(examples_raw, str):
        examples_raw = [examples_raw]
    schema = front.get("parameters_schema") or {}
    if not isinstance(schema, Mapping):
        raise SkillParseError("parameters_schema must be a mapping (a JSON schema object)")
    metadata = {k: v for k, v in front.items() if k not in KNOWN_KEYS}
    return Skill(
        key=resolved_key,
        name=str(front.get("name") or ""),
        description=str(front.get("description") or ""),
        instructions=body,
        when_to_use=str(front.get("when_to_use") or ""),
        version=str(front.get("version", "1")),
        examples=tuple(str(e) for e in examples_raw),
        parameters_schema=dict(schema),
        requires=SkillRequirements.from_mapping(front.get("requires")),
        resources=_resources_from(front.get("resources")),
        metadata=metadata,
    )


def load_skill(directory: Path | str, *, key: str | None = None, filename: str = "SKILL.md") -> Skill:
    """A :class:`Skill` from a directory holding ``SKILL.md`` and its declared resources.

    Resources are attached as lazy loaders (read when first asked for); a declared resource
    that is not on disk is refused now, because a skill promising a checklist it cannot produce
    would fail on the model's turn instead of the author's.
    """
    root = Path(directory)
    text = (root / filename).read_text(encoding="utf-8")
    skill = parse_skill(text, key=key or root.name)
    attached: dict[str, SkillResource] = {}
    for path, resource in skill.resources.items():
        file = root / path
        if not file.is_file():
            raise SkillParseError(f"skill {skill.key!r} declares resource {path!r} but {file} is not a file")

        def loader(p: Path = file) -> str:
            return p.read_text(encoding="utf-8")

        attached[path] = SkillResource(
            path=path,
            kind=resource.kind,
            description=resource.description,
            media_type=resource.media_type,
            loader=loader,
        )
    return skill.with_resources(attached)
