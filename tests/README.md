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
