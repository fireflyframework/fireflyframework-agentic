# software_factory

Example application showing how to run `FireflyAgent` instances as GitHub Actions using the `fireflyframework-agentic` library.

## Structure

```
software_factory/
├── action_runtime/      # Runtime that bridges GitHub Actions env ↔ FireflyAgent
├── tests/               # Unit tests for the action_runtime
└── Dockerfile           # Base image: FROM this + CMD ["--agent", "<name>"]
```

## Docker image

Each agent action's Dockerfile is just:

```dockerfile
FROM ghcr.io/fireflyframework/factory-base:<tag>
CMD ["--agent", "<agent-name>"]
```

The base image ships:

- Python 3.13-slim
- `fireflyframework-agentic` (the framework)
- `software_factory` (this example, on PYTHONPATH)
- `gh` CLI + `git`
- A non-root `runner` user

The entrypoint is `python -m software_factory.action_runtime`.
Tag scheme: CalVer (`YYYY.MM.PP`) plus `<sha>`.

## Running tests

From the repo root:

```bash
pytest examples/software_factory/tests
```
