# software_factory

Example application showing how to run `FireflyAgent` instances as GitHub Actions using the `fireflyframework-agentic` library.

## Structure

```
software_factory/
├── artifact.py          # $RUNNER_TEMP-backed artifact store
├── env.py               # GitHub Actions INPUT_* env var reader
├── exceptions.py        # ActionRuntimeError hierarchy
├── feedback.py          # QA feedback loader for retry iterations
├── github_outputs.py    # $GITHUB_OUTPUT writer
├── io_models.py         # RunResult Pydantic model
├── runner.py            # Orchestrates a full agent run
├── __main__.py          # CLI: python -m software_factory --agent <name>
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

The entrypoint is `python -m software_factory`.
Tag scheme: CalVer (`YYYY.MM.PP`) plus `<sha>`.

## Running tests

From the repo root:

```bash
pytest tests/examples/software_factory
```
