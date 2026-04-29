# Tests

The test suite is organized by **purpose**, with the PR-gate vs nightly split controlled by the `@pytest.mark.nightly` marker.

## Categories

| Folder | What goes here |
|---|---|
| `unit/` | Pure logic. No real network, DB, or LLM calls. Mocks/fakes are fine. ~95% of the suite today. |
| `integration/` | Multiple subsystems wired together (e.g. agent + middleware + memory + pipeline). Mocks at external boundaries are still allowed. |
| `functional/` | A user-facing feature exercised end-to-end ("the agent completes workflow X"). |
| `performance/` | Benchmarks (`pytest-benchmark`). Files must be named `test_bench_*.py` so pytest's default collection picks them up. Marked `@pytest.mark.nightly`. |
| `security/` | Defenses against attackers (SQL injection, prompt injection, RBAC, encryption). |
| `data_validation/` | Schema, contract, and configuration validation. |
| `responsible_ai/` | Safety of the system itself: PII in outputs, content filtering, fairness. |

`integration/` is about **wiring**; `functional/` is about **product behavior**. `security/` is about **adversaries**; `responsible_ai/` is about the **system not misbehaving on its own**.

The taxonomy is adapted from [Recommenders](https://github.com/recommenders-team/recommenders). Definitions below follow Recommenders' wording, narrowed to an agentic framework.

### `unit/` — unit tests

Tests that make sure individual Python utilities and components run correctly. Unit tests are fast (ideally each one well under one second), have no external dependencies (no real network, DB, or LLM calls), and run in every pull request. They are the bulk of the suite — about 95% of the tests today.

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

## The `@pytest.mark.nightly` marker

Tests that need real LLM/DB/HTTP infrastructure (or otherwise take long enough that they don't belong in PR CI) get marked:

```python
import pytest

@pytest.mark.nightly
async def test_real_postgres_round_trip():
    ...
```

The marker goes on **functions or classes only**, never via `pytestmark` at file level. Grep the suite to enumerate exactly what runs at night:

```bash
grep -rn "@pytest.mark.nightly" tests/
```

## Running tests

| Command | What it runs |
|---|---|
| `uv run pytest -m "not nightly"` | PR-gate set (default for local dev) |
| `uv run pytest` | Everything, including nightly tests |
| `uv run pytest tests/unit/agents/ -q` | Just one subsystem |
| `uv run pytest -m nightly` | Only nightly tests (e.g. to debug them) |

## CI

- `.github/workflows/pr-gate.yml` — runs on every PR targeting `main` and on manual dispatch. Executes `pytest -m "not nightly" --cov --cov-report=term-missing`.
- `.github/workflows/nightly.yml` — runs daily at 03:00 UTC and on manual dispatch. Executes `pytest --cov --cov-report=term-missing --durations=50` (no filter).
