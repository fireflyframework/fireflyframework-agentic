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

"""``Skill`` — a unit of know-how an agent carries, in the Agent Skills shape.

A skill is three things, and the shape matters because each goes to a different place:

* **frontmatter** — key, name, description, when to use, version, requirements, a config
  schema, examples, the resource index. Metadata a host stores, versions and shows.
* **body** — markdown instructions, a Jinja template over the skill's config. This is what
  reaches the system prompt, once per skill, rendered.
* **resources** — reference documents and templates the body points at by path. These do NOT
  reach the prompt: they are read on demand through the ``read_skill`` tool
  (:func:`~fireflyframework_agentic.skills.tool.build_read_skill_tool`), so an agent carrying
  twelve skills carries twelve bodies and no appendices, and pays for a checklist only on the
  turn it reads it. That is progressive disclosure, and it is the reason a skill is not just a
  longer prompt.

Skills are frozen values. Binding a config (:meth:`Skill.with_config`) or attaching loaded
resources (:meth:`Skill.with_resources`) returns a new skill; :meth:`Skill.digest` names one
exactly, so a host can prove that the prompt a published worker carries has not changed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import posixpath
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateError

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

ResourceKind = Literal["reference", "template", "script"]

# The body is a template over the config: an undefined variable is an authoring error, not an
# empty string in a partner-facing memo. ``default(...)`` remains available for optional values.
_env = Environment(loader=BaseLoader(), autoescape=False, keep_trailing_newline=False, undefined=StrictUndefined)


class SkillParseError(ValueError):
    """The SKILL.md (or the frontmatter given in code) is not a skill."""


class SkillConfigError(ValueError):
    """A config does not satisfy the skill's ``parameters_schema``.

    Carries every problem, so an editor can show them all at once.
    """

    def __init__(self, key: str, problems: list[str]) -> None:
        self.key = key
        self.problems = list(problems)
        super().__init__(f"skill {key!r}: config invalid: " + "; ".join(problems))


def _frozen(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def validate_resource_path(path: str) -> str:
    """A resource path is relative, POSIX, inside the skill, and not empty.

    A skill's resources are the files it declares, not the directory it lives in: ``..`` and an
    absolute path would turn ``read_skill`` into a file share.
    """
    if not isinstance(path, str) or not path.strip():
        raise SkillParseError("a resource path must be a non-empty string")
    normalised = posixpath.normpath(path.strip().replace("\\", "/"))
    if normalised.startswith(("/", "../")) or normalised == ".." or normalised == "." or "\x00" in normalised:
        raise SkillParseError(f"resource path {path!r} escapes the skill; paths are relative and stay inside it")
    return normalised


@dataclass(frozen=True)
class SkillResource:
    """One file a skill points at: a reference, a template, or a script.

    Content is inline (``content``) or lazy (``loader``); :meth:`read` returns it and caches a
    loaded value. ``kind`` is advisory — a host decides whether a script may run; the framework
    only ever READS resources.
    """

    path: str
    kind: ResourceKind = "reference"
    description: str = ""
    content: str | None = None
    loader: Callable[[], str] | None = field(default=None, repr=False, compare=False)
    media_type: str = "text/markdown"
    _cache: dict[str, str] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_resource_path(self.path))

    def read(self) -> str:
        """The resource text."""
        if self.content is not None:
            return self.content
        if "text" in self._cache:
            return self._cache["text"]
        if self.loader is None:
            raise LookupError(f"resource {self.path!r} has no content and no loader")
        text = self.loader()
        self._cache["text"] = text
        return text

    @property
    def available(self) -> bool:
        return self.content is not None or self.loader is not None


@dataclass(frozen=True)
class SkillRequirements:
    """What a skill needs from its host to be usable: tool names, connector kinds, other skills."""

    tools: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()

    def any(self) -> bool:
        return bool(self.tools or self.connectors or self.skills)

    @classmethod
    def from_mapping(cls, raw: Any) -> SkillRequirements:
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise SkillParseError("requires must be a mapping with tools / connectors / skills lists")
        unknown = set(raw) - {"tools", "connectors", "skills"}
        if unknown:
            raise SkillParseError(f"requires has unknown keys {sorted(unknown)}")

        def names(field_name: str) -> tuple[str, ...]:
            value = raw.get(field_name) or ()
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, Iterable) or any(not isinstance(v, str) or not v for v in value):
                raise SkillParseError(f"requires.{field_name} must be a list of names")
            return tuple(value)

        return cls(tools=names("tools"), connectors=names("connectors"), skills=names("skills"))


@dataclass(frozen=True)
class Skill:
    """See the module docstring. Build one with :func:`parse_skill` / :func:`load_skill`, or in code."""

    key: str
    name: str
    description: str
    instructions: str = ""
    when_to_use: str = ""
    version: str = "1"
    examples: tuple[str, ...] = ()
    parameters_schema: Mapping[str, Any] = field(default_factory=dict)
    requires: SkillRequirements = field(default_factory=SkillRequirements)
    resources: Mapping[str, SkillResource] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not KEY_PATTERN.match(self.key):
            raise SkillParseError(f"skill key {self.key!r} must match {KEY_PATTERN.pattern}")
        if not self.name or not isinstance(self.name, str):
            raise SkillParseError(f"skill {self.key!r} needs a name")
        if not self.description or not isinstance(self.description, str):
            raise SkillParseError(f"skill {self.key!r} needs a description")
        object.__setattr__(self, "examples", tuple(self.examples))
        object.__setattr__(self, "parameters_schema", _frozen(self.parameters_schema))
        object.__setattr__(self, "config", _frozen(self.config))
        object.__setattr__(self, "metadata", _frozen(self.metadata))
        resources = {}
        for path, resource in dict(self.resources).items():
            normalised = validate_resource_path(path)
            if resource.path != normalised:
                raise SkillParseError(f"resource {path!r} is registered under a different path {resource.path!r}")
            resources[normalised] = resource
        object.__setattr__(self, "resources", MappingProxyType(resources))
        object.__setattr__(self, "version", str(self.version))

    # -- values --------------------------------------------------------------

    def with_config(self, config: Mapping[str, Any] | None) -> Skill:
        """The same skill bound to ``config`` (validated on render)."""
        return _replace(self, config=_frozen(config))

    def with_resources(self, resources: Mapping[str, SkillResource]) -> Skill:
        """The same skill with these resources attached.

        The index is REPLACED — a resource the frontmatter declared and this call omits is gone —
        but a resource the frontmatter declared keeps its declared kind and description when the
        attached object carries none: the frontmatter is where an author describes a resource,
        and a loader that only knows the bytes should not erase that.
        """
        attached: dict[str, SkillResource] = {}
        for path, resource in resources.items():
            declared = self.resources.get(validate_resource_path(path))
            if declared is not None:
                resource = SkillResource(
                    path=resource.path,
                    kind=declared.kind if resource.kind == "reference" else resource.kind,
                    description=resource.description or declared.description,
                    content=resource.content,
                    loader=resource.loader,
                    media_type=resource.media_type if resource.media_type != "text/markdown" else declared.media_type,
                )
            attached[path] = resource
        return _replace(self, resources=MappingProxyType(attached))

    def digest(self) -> str:
        """SHA-256 over everything the model can see: frontmatter, body, config, resource texts.

        A host stores it on a published worker to prove later that editing the skill did not
        change what the worker runs with.
        """
        payload = {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "version": self.version,
            "instructions": self.instructions,
            "examples": list(self.examples),
            "parameters_schema": dict(self.parameters_schema),
            "requires": {
                "tools": self.requires.tools,
                "connectors": self.requires.connectors,
                "skills": self.requires.skills,
            },
            "config": dict(self.config),
            "resources": {
                path: {"kind": r.kind, "description": r.description, "text": r.read() if r.available else None}
                for path, r in sorted(self.resources.items())
            },
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    # -- config --------------------------------------------------------------

    def validate_config(self, config: Mapping[str, Any] | None = None) -> list[str]:
        """Every way ``config`` (default: the bound config) fails ``parameters_schema``; empty when valid.

        The admitted schema subset is the one an editor can render as a form: ``type`` (string,
        number, integer, boolean, array, object), ``required``, ``properties`` with ``enum``,
        ``minimum`` / ``maximum``, ``minLength`` / ``maxLength``, ``default``, and
        ``additionalProperties: false``. Anything else in the schema is carried, not enforced.
        """
        values = dict(self.config if config is None else config)
        schema = self.parameters_schema
        if not schema:
            return []
        problems: list[str] = []
        properties: Mapping[str, Any] = schema.get("properties") or {}
        for name in schema.get("required") or ():
            if name not in values:
                problems.append(f"{name} is required")
        if schema.get("additionalProperties") is False:
            for name in values:
                if name not in properties:
                    problems.append(f"{name} is unexpected (not in the schema)")
        for name, rule in properties.items():
            if name not in values or not isinstance(rule, Mapping):
                continue
            problems.extend(f"{name} {p}" for p in _check_value(values[name], rule))
        return problems

    def _config_with_defaults(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        values = dict(self.config if config is None else config)
        properties: Mapping[str, Any] = self.parameters_schema.get("properties") or {}
        for name, rule in properties.items():
            if name not in values and isinstance(rule, Mapping) and "default" in rule:
                values[name] = rule["default"]
        return values

    # -- requirements --------------------------------------------------------

    def unmet(
        self,
        *,
        tools: Iterable[str] = (),
        connectors: Iterable[str] = (),
        skills: Iterable[str] = (),
    ) -> SkillRequirements:
        """The requirements the host does not satisfy."""
        have_tools, have_connectors, have_skills = set(tools), set(connectors), set(skills)
        return SkillRequirements(
            tools=tuple(t for t in self.requires.tools if t not in have_tools),
            connectors=tuple(c for c in self.requires.connectors if c not in have_connectors),
            skills=tuple(s for s in self.requires.skills if s not in have_skills),
        )

    # -- rendering -----------------------------------------------------------

    def render(self, config: Mapping[str, Any] | None = None) -> str:
        """The body with ``config`` (default: the bound config, plus schema defaults) substituted.

        Raises :class:`SkillConfigError` when the config fails the schema — a body rendered
        from a wrong config is worse than no body, because the model would follow it.
        """
        problems = self.validate_config(config)
        if problems:
            raise SkillConfigError(self.key, problems)
        values = self._config_with_defaults(config)
        try:
            return _env.from_string(self.instructions).render(**values).strip()
        except TemplateError as exc:
            raise SkillConfigError(self.key, [f"body could not be rendered: {exc}"]) from exc


def _replace(skill: Skill, **changes: Any) -> Skill:
    return dataclasses.replace(skill, **changes)


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict, Mapping),
}


def _check_value(value: Any, rule: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    expected = rule.get("type")
    if isinstance(expected, str) and expected in _TYPES:
        ok = isinstance(value, _TYPES[expected]) and not (expected in ("number", "integer") and isinstance(value, bool))
        if not ok:
            problems.append(f"must be a {expected}, got {type(value).__name__}")
            return problems
    if "enum" in rule and value not in rule["enum"]:
        problems.append(f"must be one of {list(rule['enum'])}, got {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            problems.append(f"must be >= {rule['minimum']}, got {value}")
        if "maximum" in rule and value > rule["maximum"]:
            problems.append(f"must be <= {rule['maximum']}, got {value}")
    if isinstance(value, str):
        if "minLength" in rule and len(value) < rule["minLength"]:
            problems.append(f"must be at least {rule['minLength']} characters")
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            problems.append(f"must be at most {rule['maxLength']} characters")
    return problems
