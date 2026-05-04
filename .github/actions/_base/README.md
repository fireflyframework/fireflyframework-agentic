# factory-base

Base Docker image for all factory agent actions. Each agent action's
`Dockerfile` is just:

    FROM ghcr.io/fireflyframework/factory-base:<tag>
    CMD ["--agent", "<agent-name>"]

The image ships:

- Python 3.13-slim
- `fireflyframework-agentic[factory]` (this repo at the build SHA)
- `gh` CLI (used by codegen + qa)
- `git`
- A non-root `runner` user

The entrypoint is `python -m fireflyframework_agentic.factory.action_runtime`.
Tag scheme: CalVer (`YYYY.MM.PP`) plus `<sha>`.
