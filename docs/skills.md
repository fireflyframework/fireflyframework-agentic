---
title: Skills
description: Units of know-how an agent carries — frontmatter, a body rendered over a config, and resources read on demand.
---

# Skills

A **skill** is a unit of know-how in the Agent Skills shape: YAML frontmatter, a markdown body,
and resources. The three go to three different places, and that is the point:

| Part | Where it goes | Why |
|---|---|---|
| frontmatter (`key`, `name`, `description`, `when_to_use`, `version`, `requires`, `parameters_schema`, `examples`, the resource index) | your store, your editor, the prompt's heading | metadata a host versions and shows |
| body (markdown, a Jinja template over the skill's config) | the system prompt, once per skill, rendered | what the model follows |
| resources (reference documents, templates) | **not** the prompt — fetched through the `read_skill` tool on the turn they are needed | an agent with twelve skills carries twelve bodies and no appendices |

That last row is progressive disclosure, and it is why a skill is not just a longer prompt.

## Author one

`SKILL.md`:

```markdown
---
name: Local GAAP close
description: Close the books under local GAAP with the firm's checklist.
when_to_use: When a client asks for a month-end or year-end close under local GAAP.
version: 3
requires:
  tools: [dw_workspace_write]
parameters_schema:
  type: object
  required: [entity]
  properties:
    entity: {type: string, description: The legal entity being closed.}
    fiscal_year_end: {type: string, enum: ["12-31", "06-30"], default: "12-31"}
  additionalProperties: false
resources:
  checklist.md: A step-by-step close checklist.
  templates/memo.md: {kind: template, description: The close memo the partner signs.}
---
# Closing under local GAAP

You are closing **{{ entity }}** with a fiscal year ending {{ fiscal_year_end }}.
Read `checklist.md` before starting.
```

```python
from fireflyframework_agentic.skills import load_skill, parse_skill

skill = load_skill("skills/x_local_gaap")          # SKILL.md + the declared resources, loaded lazily
skill = parse_skill(text, key="x_local_gaap")       # text only; attach resources with with_resources()
```

- The key matches `^[a-z][a-z0-9_]*$`; it comes from `key=` or the frontmatter's `key`.
- Resource paths are relative and stay inside the skill: `..` and absolute paths are refused, and
  `load_skill` exposes only the resources the frontmatter declares — the directory is not a file share.
- Frontmatter keys the framework does not read are kept under `skill.metadata`.

## Bind and render

```python
bound = skill.with_config({"entity": "Acme SL"})
bound.render()                      # the body with the config and schema defaults substituted
skill.validate_config({...})        # every problem at once, [] when valid
skill.unmet(tools={...}, connectors={...}, skills={...})   # what the host does not provide
skill.digest()                      # SHA-256 over everything the model can see
```

`parameters_schema` is the JSON-schema subset an editor can render as a form — `type`,
`required`, `properties` with `enum`, `minimum`/`maximum`, `minLength`/`maxLength`, `default`,
`additionalProperties: false`. A config that fails it raises `SkillConfigError` on render, because
a body rendered from a wrong config is worse than no body. The body is a Jinja template with
`StrictUndefined`: an undefined variable is an authoring error, and `{{ x | default(...) }}` covers
optional values.

## Put it on an agent

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.skills import build_read_skill_tool, render_skills_section

skills = [skill.with_config({"entity": "Acme SL"})]
agent = FireflyAgent(
    "closer",
    model=model,
    instructions="You are a careful accountant.\n\n" + render_skills_section(skills),
    tools=[build_read_skill_tool(skills)],
)
```

`render_skills_section` produces a `## Skills` section: one `###` per skill with its key, version,
when-to-use and rendered body, followed by the resource list as the exact
`read_skill(key="…", path="…")` calls that fetch them. `read_skill` is a plain `BaseTool` — no
approval, no side effects, reads only what the skills declared, answers a wrong key or path with a
`ModelRetry` naming what exists, lists a skill's resources when `path` is empty, and cuts a long
resource at `max_chars` saying so. Pass `listeners=` so a host's ledger sees these reads like any
other call.
