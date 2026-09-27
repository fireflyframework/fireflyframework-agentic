# Tests

The test suite is organized by **purpose** (Recommenders-style categories) and split between **PR-gate** and **nightly** runs via the `@pytest.mark.nightly` marker.

## PR-gate vs nightly

- **PR-gate** runs on every pull request without provider API keys or externally managed services. Most tests use local fixtures; PostgreSQL integration tests start an isolated Testcontainers database through Docker. Images may be downloaded on first use. Its job is to catch breaking changes before merge. A test runs in PR-gate by default.
- **Nightly** runs once a day on `main` (and on manual dispatch). It runs the entire suite — everything PR-gate runs **plus** anything decorated with `@pytest.mark.nightly`. The nightly bucket is for tests that are too slow, too expensive, too flaky on shared runners, or too dependent on real infrastructure to belong on the PR critical path. Examples: benchmarks (timing-sensitive), real LLM/DB/HTTP integration tests, long end-to-end flows, fairness probes that hit a real model.

A test opts into nightly-only by adding `@pytest.mark.nightly` to its function or class. Anything without the marker stays in both runs.

### Local PostgreSQL integration

`tests/integration/test_pgvector_store.py` uses a disposable
`pgvector/pgvector:pg16` container to validate vector search and PostgreSQL memory
persistence through real drivers. Docker must be running, and the environment
must include the `[vectorstores-pgvector]` extra. Tests use isolated tables/schemas
and close their pools, container, and Testcontainers supervisor on shutdown.

```bash
uv run pytest tests/integration/test_pgvector_store.py -q
```

Without Docker, run `uv run pytest -m "not nightly and not integration"`.
That deselects integration-marked cases; it does not establish PostgreSQL
compatibility. MongoDB memory and Redis checkpoint tests replace the external
driver boundary and do not establish behavior against deployed services.

### Live model tests

`tests/integration/test_real_anthropic_e2e.py` exercises the whole stack — agent + tools, structured output, streaming, multi-turn memory, a reasoning pattern, a pipeline, a Dynamic Workflow, and cost tracking — against a **real Anthropic model**. These tests are `@pytest.mark.nightly` and **skip** unless a real `ANTHROPIC_API_KEY` is present (the suite's conftest defaults the value to `"test"` for offline runs, which the live tests treat as "no key"). Run them with:

```bash
uv run pytest tests/integration/test_real_anthropic_e2e.py -m nightly
```

`tests/integration/test_real_openai_e2e.py` makes **real, billable OpenAI requests**
through Chat Completions and Responses. Its nightly tests skip without a usable
`OPENAI_API_KEY`; configure that key in the environment before running them:

```bash
uv run pytest tests/integration/test_real_openai_e2e.py -m nightly -q
```

Both APIs default to `gpt-6-luna`. Override unprefixed model IDs with
`FIREFLY_OPENAI_CHAT_MODEL` and `FIREFLY_OPENAI_RESPONSES_MODEL`. The Chat model
must support function calling with reasoning effort `none`. The suite covers tools
and token/cost tracking, native structured output, streaming follow-up turns, and
conversation export/import. Responses export/import also exercises reasoning with
`openai_store=False`.

Live results apply to the selected models and account. A skipped suite is not
evidence of provider compatibility or account access.

### Offline OpenAI compatibility tests

`tests/integration/test_openai_api_compatibility.py` uses the real Pydantic AI and
OpenAI SDK request/response path with a mocked HTTP transport. It checks endpoint
selection, tool-call continuation, native structured output, both streaming modes,
usage, native web-search capability wiring, and conversation-memory serialization
across Chat Completions and Responses, including Responses reasoning state and
interrupted-stream handling. It runs in the PR gate without API credentials
or external requests:

```bash
uv run pytest tests/integration/test_openai_api_compatibility.py -q
```

These tests validate the framework/SDK boundary with controlled fixtures. They do
not call OpenAI or prove that every model, Azure deployment, or compatible endpoint
supports a feature. Other offline integration tests use `TestModel` or mocked
dependencies; their role is different from the credential-gated live suites.

`tests/integration/test_sync_http_connections.py` additionally exercises repeated
synchronous calls over real HTTP/1.1 keepalive connections to a local server.
It checks both APIs from ordinary synchronous code and a notebook-style running
event loop, without contacting a provider.

### Optional evaluation compatibility tests

Install the compatible `[evaluation]` extra to exercise the actual Ragas metric
adapters with deterministic model and embedding responses:

```bash
uv run --extra evaluation pytest tests/unit/evaluation/ -q
```

The suite checks metric results, explicit OpenAI API selection, embedding adapters,
and that Ragas import preserves asyncio. These tests make no live model calls;
Ragas-specific checks skip when the extra is absent. The extra deliberately uses
Ragas 0.2.6 and LangChain Community 0.3.x because newer combinations conflict with
the upgraded SDK or modify asyncio at import. See the
[dependency caveat](../docs/migration.md#optional-evaluation-dependencies).

### Portable API and documentation contracts

`tests/integration/test_model_abstraction.py` runs the same Firefly application
through Chat Completions, Responses, and Anthropic using actual SDKs with an
in-process HTTP transport. It verifies Firefly tools, memory, plain Pydantic output
schemas, `ModelOptions`, provider switching, native-setting precedence, and cache
separation by API. The model-options unit tests also check provider capability
errors, explicit configuration limits, and per-run overrides across all run modes.

`tests/integration/test_documentation_contract.py` parses the Python snippets in
the current guides, checks their Firefly imports against the installed source,
and rejects empty concrete function examples. Protocol and abstract-method
declarations remain valid interface documentation. This is a syntax/import check;
behavior is exercised separately by the example and integration tests.

`tests/integration/test_examples_offline.py` imports executable examples without
provider credentials or network access and exercises their local workflow logic,
including quota enforcement, batch inputs, and artifact integrity checks.

`tests/examples/software_factory/` validates generated source, actual build/QA
results, release artifacts, and checkpoint recovery for the runnable software
factory. These tests run offline with temporary directories.

```bash
uv run pytest tests/integration/test_documentation_contract.py tests/integration/test_examples_offline.py tests/integration/test_model_abstraction.py tests/examples/ -q
uv tool run --with-requirements docs/requirements.txt mkdocs build --strict
```

## Categories

The taxonomy is adapted from [Recommenders](https://github.com/recommenders-team/recommenders). Definitions follow Recommenders' wording, narrowed to an agentic framework.

### `unit/` — unit tests

Tests that make sure individual Python utilities and components run correctly. Unit tests are fast (ideally each one well under one second), use local files or controlled boundaries rather than external services or LLM calls, and run in every pull request. SQLite tests use real temporary databases.

### `integration/` — integration tests

Tests that make sure the **interaction between different components** is correct. They wire several subsystems together (for example: an agent + memory manager + pipeline + middleware) and verify the boundaries hold. Mocks at the outermost edges (LLM provider, external HTTP) are still allowed; what matters is that the internal wiring is exercised, not isolated.

### `functional/` — functional tests

Tests that make sure the components of the project not just run but their **function is correct**. In our context, this means end-to-end flows: an agent given a task completes the workflow and produces the expected outcome. These are user-facing feature tests, not wiring tests.

### `performance/` — performance tests

Tests that **measure the computation time or memory footprint of a piece of code and make sure that this is bounded between some limits**. We use `pytest-benchmark`. Files must be named `test_bench_*.py` so pytest's default collection picks them up. All performance tests are marked `@pytest.mark.nightly` because timing measurements are unstable on shared PR runners; they belong in scheduled runs.

### `security/` — security tests

Tests that **make sure that the code is not vulnerable to attacks**. Adversarial threat model: someone is trying to abuse the system. SQL injection, prompt injection, authentication bypass, RBAC enforcement, encryption boundaries.

### `data_validation/` — data validation tests

Tests that **ensure that the schema for input and output data for each function in the pipeline matches the desired prespecified schema, that the data is available and has the correct size**. Pydantic models, configuration validation, contracts between modules.

### `responsible_ai/` — responsible AI tests

Tests that **enforce fairness, transparency, explainability, human-centeredness, and privacy**. Not about adversaries; about the system not misbehaving on its own. PII leakage in LLM outputs, content safety filtering, bias in routing decisions, audit-trail completeness.

## Applying the `@pytest.mark.nightly` marker

```python
import os

import pytest

from fireflyframework_agentic.agents import FireflyAgent

@pytest.mark.nightly
async def test_live_response():
    if not os.environ.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"] == "test":
        pytest.skip("A real OpenAI API key is required")
    agent = FireflyAgent("live-check", model="openai-responses:gpt-6-luna", auto_register=False)
    result = await agent.run("Reply with one short greeting.")
    assert isinstance(result.output, str) and result.output.strip()
```

The example above makes a billable request when credentials are configured. The
marker goes on **functions or classes only**, never via `pytestmark` at file level.
List the nightly declarations with:

```bash
rg -n "@pytest.mark.nightly" tests/
```

## Running tests

| Command | What it runs |
|---|---|
| `uv run pytest -m "not nightly"` | PR-gate set (default for local dev) |
| `uv run pytest -m "not nightly and not integration"` | Local subset when Docker is unavailable |
| `uv run pytest` | Everything, including nightly tests |
| `uv run pytest tests/unit/agents/ -q` | Just one subsystem |
| `uv run pytest -m nightly` | Only nightly tests (e.g. to debug them) |

## CI

- `.github/workflows/pr-gate.yml` — runs on PRs targeting `main`, including documentation changes, and on manual dispatch. Executes `pytest -m "not nightly" --cov --cov-report=term-missing`, lint/type checks, and a strict documentation build before package building.
- `.github/workflows/nightly.yml` — runs daily at 03:00 UTC and on manual dispatch. Executes `pytest --cov --cov-report=term-missing --durations=50` (no filter).
- The local pre-push hook runs every non-nightly test category, including example tests.
