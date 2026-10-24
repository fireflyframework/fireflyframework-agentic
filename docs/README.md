> [!IMPORTANT]
> **Moved to pyfly: `pyfly.agentic`.** Active development continues in
> [fireflyframework-pyfly](https://github.com/fireflyframework/fireflyframework-pyfly), starting with
> [pyfly v26.10.08](https://github.com/fireflyframework/fireflyframework-pyfly/releases/tag/v26.10.08) (package version `26.10.8`).
> Use the [native Agentic documentation](https://fireflyframework.github.io/fireflyframework-pyfly/docs/modules/agentic/) and
> [migration guide](https://fireflyframework.github.io/fireflyframework-pyfly/docs/modules/agentic/migration/). This repository, its releases and the
> standalone documentation below are retained as historical material.
> Replace `fireflyframework_agentic` imports with `pyfly.agentic`,
> `FireflyAgent` with `Agent`, `BaseTool` with `AgentTool`, and
> `@firefly_agent` / `@firefly_tool` with `@agent` / `@agent_tool`.
> The native module provides no aliases for the old namespace or names.

```bash
python -m pip install "pyfly[agentic] @ https://github.com/fireflyframework/fireflyframework-pyfly/releases/download/v26.10.08/pyfly-26.10.8-py3-none-any.whl"
```

Enable `pyfly.agentic.enabled: true` in your pyfly application. Rename
`FIREFLY_AGENTIC_*` settings to `PYFLY_AGENTIC_*` and select namespaced integration
extras such as `agentic-postgres`. Follow the migration guide for configuration,
application-owned runtime services, plugins and persistent data.

---

# Historical standalone Agentic documentation

Start with the [published documentation](https://fireflyframework.github.io/fireflyframework-agentic/)
or follow the same guides here on GitHub.

## Choose a path

| Goal | Read |
|---|---|
| Install a published version | [Installation](getting-started/installation.md) |
| Run an agent with a tool and memory | [Quick start](getting-started/quickstart.md) |
| Understand the framework visually | [Visual guide](diagrams.md), [Architecture](architecture.md) |
| Select a model, API and typed options | [Models](models.md), [Migration](migration.md) |
| Build a complete application | [Tutorial](tutorial.md), [IDP walkthrough](use-case-idp.md) |
| Define application behavior | [Agents](agents.md), [Tools](tools.md), [Skills](skills.md), [Prompts](prompts.md), [Templates](templates.md) |
| Retain context and retrieve knowledge | [Memory](memory.md), [Content](content.md), [Embeddings](embeddings.md), [Vector stores](vectorstores.md) |
| Add reasoning and quality checks | [Reasoning](reasoning.md), [Validation](validation.md), [Evaluation](evaluation.md) |
| Coordinate work | [Pipelines](pipeline.md), [Workflows](workflows.md) |
| Operate an application | [Observability](observability.md), [Resilience](resilience.md), [Storage](storage.md), [Security](security.md), [Execution](execution.md), [Explainability](explainability.md) |
| Compare approaches | [Experiments](experiments.md), [Lab](lab.md) |
| Run in a notebook | [Jupyter](getting-started/jupyter.md) |

Examples and their setup requirements live in the [example catalogue](../examples/README.md).
Studio has its own [repository](https://github.com/fireflyframework/fireflyframework-agentic-studio).

## Contributing documentation

Keep examples at the Firefly application boundary unless explaining a native
integration. State which behavior is automatic, optional or application-managed.
Preserve the distinction between Chat Completions and Responses, and between
process-local conversation history and persistent working memory.

Use a diagram when relationships or control flow are clearer visually. Keep each
figure focused, explain its meaning in adjacent prose, and link to the relevant
API guide. Include descriptive alt text and a full-size link for SVGs. Regenerate
branded assets through the [asset generator](../assets/README.md), rather than
editing their generated SVGs.

Run from the repository root:

```bash
python assets/tools/build_brand_assets.py --check
uv tool run --with-requirements docs/requirements.txt mkdocs build --strict
python scripts/check_docs.py
uv run --no-project --with playwright==1.63.0 python -m playwright install chromium
uv run --no-project --with playwright==1.63.0 python scripts/check_docs.py --browser
```

The static check follows local links, image paths and HTML fragments in the built
site. The browser check renders every Mermaid diagram using the site's actual
Material integration and fails on missing or invalid diagrams. It also checks
keyboard-operated expand/fit controls at desktop and mobile widths. It requires
network access for the same CDN resources used by the site. These checks run in
the pull-request gate and before Pages deployment.

For local preview:

```bash
uv tool run --with-requirements docs/requirements.txt mkdocs serve
```

See [CONTRIBUTING](../CONTRIBUTING.md) for the full development gate. Release
versions use **YY.MM.Patch**; documentation-only updates can deploy independently
of a package release. Update [mkdocs.yml](../mkdocs.yml) when adding a page and
keep the root README, landing page and guides consistent.
