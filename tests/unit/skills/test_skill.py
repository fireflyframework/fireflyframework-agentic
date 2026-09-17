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

"""The ``Skill`` primitive: an Agent-Skills-style unit of know-how with progressive disclosure.

A skill is frontmatter (key, name, description, when to use, version, requirements, a config
schema), a markdown body of instructions, and resources — reference documents and templates the
body points at. The body goes into the system prompt; the resources do not: they are read on
demand through a ``read_skill`` tool, so a worker carrying twelve skills does not carry twelve
skills' worth of appendices on every turn. This suite pins the frontmatter contract, the body
rendering with config substitution, the resources, the prompt section and the tool.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai import ModelRetry

from fireflyframework_agentic.skills import (
    Skill,
    SkillConfigError,
    SkillParseError,
    SkillRequirements,
    SkillResource,
    build_read_skill_tool,
    load_skill,
    parse_skill,
    render_skills_section,
)

SKILL_MD = """---
name: Local GAAP close
description: Close the books under local GAAP with the firm's checklist.
when_to_use: When a client asks for a month-end or year-end close under local GAAP.
version: 3
requires:
  tools: [dw_workspace_write, dw_knowledge_search]
  connectors: [sharepoint]
  skills: [x_ifrs_bridge]
parameters_schema:
  type: object
  required: [entity]
  properties:
    entity:
      type: string
      description: The legal entity being closed.
    fiscal_year_end:
      type: string
      enum: [12-31, 06-30]
      default: 12-31
    materiality_eur:
      type: integer
      minimum: 0
  additionalProperties: false
examples:
  - "Close FY2025 for Acme SL"
resources:
  checklist.md: A step-by-step close checklist.
  templates/memo.md:
    kind: template
    description: The close memo the partner signs.
---
# Closing under local GAAP

You are closing **{{ entity }}** with a fiscal year ending {{ fiscal_year_end }}.

1. Read the checklist (`checklist.md`) before starting.
2. Anything above {{ materiality_eur | default(1000) }} EUR needs a memo from `templates/memo.md`.
"""


@pytest.fixture
def skill() -> Skill:
    parsed = parse_skill(SKILL_MD, key="x_local_gaap")
    return parsed.with_resources(
        {
            "checklist.md": SkillResource(path="checklist.md", content="1. Reconcile bank.\n2. Accrue.\n"),
            "templates/memo.md": SkillResource(
                path="templates/memo.md", kind="template", content="# Close memo\n\nEntity: ...\n"
            ),
        }
    )


class TestParse:
    def test_frontmatter_fields(self, skill: Skill) -> None:
        assert skill.key == "x_local_gaap"
        assert skill.name == "Local GAAP close"
        assert skill.description.startswith("Close the books")
        assert skill.when_to_use.startswith("When a client asks")
        assert skill.version == "3"
        assert skill.requires == SkillRequirements(
            tools=("dw_workspace_write", "dw_knowledge_search"), connectors=("sharepoint",), skills=("x_ifrs_bridge",)
        )
        assert skill.parameters_schema["required"] == ["entity"]
        assert skill.examples == ("Close FY2025 for Acme SL",)
        assert skill.instructions.startswith("# Closing under local GAAP")

    def test_resources_declared_in_frontmatter_are_known_before_they_are_loaded(self) -> None:
        parsed = parse_skill(SKILL_MD, key="x_local_gaap")
        assert set(parsed.resources) == {"checklist.md", "templates/memo.md"}
        assert parsed.resources["templates/memo.md"].kind == "template"
        assert parsed.resources["templates/memo.md"].description == "The close memo the partner signs."
        assert parsed.resources["checklist.md"].kind == "reference"
        assert parsed.resources["checklist.md"].description == "A step-by-step close checklist."

    def test_the_key_comes_from_the_frontmatter_when_not_given(self) -> None:
        parsed = parse_skill("---\nkey: x_bridge\nname: Bridge\ndescription: d\n---\nBody.\n")
        assert parsed.key == "x_bridge"
        assert parsed.instructions == "Body."

    def test_a_missing_frontmatter_is_refused(self) -> None:
        with pytest.raises(SkillParseError, match="frontmatter"):
            parse_skill("# Just a body\n", key="x")

    def test_a_skill_needs_a_name_a_description_and_a_key(self) -> None:
        with pytest.raises(SkillParseError, match="name"):
            parse_skill("---\ndescription: d\n---\nBody.\n", key="x")
        with pytest.raises(SkillParseError, match="description"):
            parse_skill("---\nname: n\n---\nBody.\n", key="x")
        with pytest.raises(SkillParseError, match="key"):
            parse_skill("---\nname: n\ndescription: d\n---\nBody.\n")
        with pytest.raises(SkillParseError, match="key"):
            parse_skill("---\nname: n\ndescription: d\n---\nBody.\n", key="Not A Key")

    def test_a_resource_path_escaping_the_skill_is_refused(self) -> None:
        with pytest.raises(SkillParseError, match="resource path"):
            parse_skill("---\nname: n\ndescription: d\nresources:\n  ../secrets.md: x\n---\nBody.\n", key="x")
        with pytest.raises(SkillParseError, match="resource path"):
            parse_skill("---\nname: n\ndescription: d\nresources:\n  /etc/passwd: x\n---\nBody.\n", key="x")


class TestRender:
    def test_the_body_is_rendered_with_the_config_and_schema_defaults(self, skill: Skill) -> None:
        text = skill.render({"entity": "Acme SL"})
        assert "closing **Acme SL** with a fiscal year ending 12-31" in text
        assert "above 1000 EUR" in text

    def test_config_is_validated_against_the_schema(self, skill: Skill) -> None:
        with pytest.raises(SkillConfigError, match="entity"):
            skill.render({})
        with pytest.raises(SkillConfigError, match="fiscal_year_end"):
            skill.render({"entity": "Acme", "fiscal_year_end": "03-31"})
        with pytest.raises(SkillConfigError, match="materiality_eur"):
            skill.render({"entity": "Acme", "materiality_eur": -5})
        with pytest.raises(SkillConfigError, match="materiality_eur"):
            skill.render({"entity": "Acme", "materiality_eur": "lots"})
        with pytest.raises(SkillConfigError, match="unexpected"):
            skill.render({"entity": "Acme", "colour": "blue"})

    def test_validate_config_reports_every_problem_at_once(self, skill: Skill) -> None:
        problems = skill.validate_config({"fiscal_year_end": "03-31", "materiality_eur": -1})
        assert len(problems) == 3
        assert skill.validate_config({"entity": "Acme"}) == []

    def test_with_config_binds_values_for_a_later_render(self, skill: Skill) -> None:
        bound = skill.with_config({"entity": "Acme SL"})
        assert bound.config == {"entity": "Acme SL"}
        assert "Acme SL" in bound.render()
        # The original is untouched: skills are values.
        assert skill.config == {}

    def test_a_skill_without_a_schema_renders_any_config(self) -> None:
        plain = parse_skill("---\nname: n\ndescription: d\n---\nHello {{ who }}.\n", key="x")
        assert plain.render({"who": "world"}) == "Hello world."

    def test_unmet_requirements_are_named(self, skill: Skill) -> None:
        unmet = skill.unmet(tools={"dw_workspace_write"}, connectors=set(), skills={"x_ifrs_bridge"})
        assert unmet == SkillRequirements(tools=("dw_knowledge_search",), connectors=("sharepoint",), skills=())
        assert unmet.any()
        assert not skill.unmet(
            tools={"dw_workspace_write", "dw_knowledge_search"}, connectors={"sharepoint"}, skills={"x_ifrs_bridge"}
        ).any()


class TestResources:
    def test_a_resource_reads_its_content_or_its_loader_once(self) -> None:
        calls = {"n": 0}

        def load() -> str:
            calls["n"] += 1
            return "loaded"

        lazy = SkillResource(path="a.md", loader=load)
        assert lazy.read() == "loaded"
        assert lazy.read() == "loaded"
        assert calls["n"] == 1
        assert SkillResource(path="b.md", content="inline").read() == "inline"

    def test_a_resource_with_nothing_to_read_says_so(self) -> None:
        with pytest.raises(LookupError, match="no content"):
            SkillResource(path="c.md").read()

    def test_load_skill_from_a_directory(self, tmp_path: Path) -> None:
        root = tmp_path / "x_local_gaap"
        (root / "templates").mkdir(parents=True)
        (root / "SKILL.md").write_text(SKILL_MD)
        (root / "checklist.md").write_text("1. Reconcile.\n")
        (root / "templates" / "memo.md").write_text("# Memo\n")
        (root / "unlisted.md").write_text("not declared\n")

        loaded = load_skill(root)
        assert loaded.key == "x_local_gaap"
        assert loaded.resources["checklist.md"].read() == "1. Reconcile.\n"
        assert loaded.resources["templates/memo.md"].read() == "# Memo\n"
        # Only declared resources are exposed: the directory is not a file share.
        assert "unlisted.md" not in loaded.resources

    def test_load_skill_refuses_a_declared_resource_that_is_missing(self, tmp_path: Path) -> None:
        root = tmp_path / "x"
        root.mkdir()
        (root / "SKILL.md").write_text("---\nname: n\ndescription: d\nresources:\n  gone.md: x\n---\nBody.\n")
        with pytest.raises(SkillParseError, match="gone.md"):
            load_skill(root, key="x")


class TestPromptSection:
    def test_progressive_disclosure(self, skill: Skill) -> None:
        other = parse_skill(
            "---\nname: IFRS bridge\ndescription: Bridge local GAAP to IFRS.\n---\nBridge it.\n", key="x_ifrs_bridge"
        )
        section = render_skills_section([skill.with_config({"entity": "Acme SL"}), other])
        assert section.startswith("## Skills")
        assert "### Local GAAP close" in section
        assert "When to use: When a client asks" in section
        assert "closing **Acme SL**" in section
        # Resources are LISTED, not inlined — that is the whole point.
        assert "checklist.md" in section
        assert "1. Reconcile bank." not in section
        assert "read_skill" in section
        assert 'read_skill(key="x_local_gaap", path="checklist.md")' in section
        assert "### IFRS bridge" in section
        assert "Bridge it." in section

    def test_an_unbound_skill_with_a_schema_renders_with_defaults_only_when_valid(self, skill: Skill) -> None:
        with pytest.raises(SkillConfigError):
            render_skills_section([skill])

    def test_no_skills_no_section(self) -> None:
        assert render_skills_section([]) == ""


class TestReadSkillTool:
    async def test_the_tool_returns_a_declared_resource(self, skill: Skill) -> None:
        tool = build_read_skill_tool([skill])
        assert tool.name == "read_skill"
        assert [p.name for p in tool.parameters] == ["key", "path"]
        assert await tool.execute(key="x_local_gaap", path="checklist.md") == "1. Reconcile bank.\n2. Accrue.\n"

    async def test_the_tool_lists_a_skill_when_no_path_is_given(self, skill: Skill) -> None:
        tool = build_read_skill_tool([skill])
        listing = await tool.execute(key="x_local_gaap", path="")
        assert "checklist.md" in listing and "templates/memo.md" in listing
        assert "The close memo the partner signs." in listing

    async def test_an_unknown_skill_or_path_tells_the_model_what_exists(self, skill: Skill) -> None:
        tool = build_read_skill_tool([skill])
        with pytest.raises(ModelRetry, match="x_local_gaap"):
            await tool.execute(key="x_nope", path="checklist.md")
        with pytest.raises(ModelRetry, match="checklist.md"):
            await tool.execute(key="x_local_gaap", path="nope.md")
        with pytest.raises(ModelRetry, match="checklist.md"):
            await tool.execute(key="x_local_gaap", path="../SKILL.md")

    async def test_a_long_resource_is_cut_at_the_limit_and_says_so(self) -> None:
        big = parse_skill(
            "---\nname: n\ndescription: d\nresources:\n  big.md: x\n---\nBody.\n", key="x"
        ).with_resources({"big.md": SkillResource(path="big.md", content="a" * 5000)})
        tool = build_read_skill_tool([big], max_chars=100)
        out = await tool.execute(key="x", path="big.md")
        assert out.startswith("a" * 100)
        assert "truncated" in out

    def test_the_tool_is_a_plain_base_tool_with_no_approval(self, skill: Skill) -> None:
        tool = build_read_skill_tool([skill])
        assert tool.requires_approval is False
        assert tool.defers is False
        assert "read_skill" in tool.description or "resource" in tool.description


class TestDataclassContract:
    def test_a_skill_is_a_frozen_value(self, skill: Skill) -> None:
        with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError, whichever dataclass raises it
            skill.name = "other"  # type: ignore[misc]

    def test_a_skill_can_be_built_in_code_without_markdown(self) -> None:
        built = Skill(key="x_code", name="Code", description="d", instructions="Do {{ thing }}.")
        assert built.render({"thing": "it"}) == "Do it."
        assert built.resources == {}
        assert built.requires == SkillRequirements()

    def test_digest_changes_with_body_config_and_resources(self, skill: Skill) -> None:
        a = skill.digest()
        assert a == skill.digest()
        assert skill.with_config({"entity": "A"}).digest() != a
        assert skill.with_resources({}).digest() != a
        assert Skill(key="x", name="n", description="d", instructions="x").digest() != a
        assert len(a) == 64
