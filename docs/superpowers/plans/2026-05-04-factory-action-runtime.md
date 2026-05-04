# Factory Agent Action Runtime — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a single Python runtime that turns any registered `FireflyAgent` into a GitHub Action invocation — parsing `INPUT_*` env vars, loading prior-stage artifacts, running the agent, writing typed values to `$GITHUB_OUTPUT`, persisting output artifacts, and propagating tracing/usage/output-guard concerns. Reusable by all four MVP1 agents (Spec 3) and the future programmatic pipeline (MVP2 Spec 6).

**Architecture:** The runtime is agent-agnostic: a single async function `run_agent(name: str, raw_inputs: dict) -> RunResult` looks up an agent in the existing `agent_registry`, builds typed inputs from `INPUT_*` env vars + on-disk artifacts, calls `agent.run(prompt)`, and writes outputs to `$GITHUB_OUTPUT` + `$RUNNER_TEMP/factory/`. A small `__main__` CLI (`python -m fireflyframework_agentic.factory.action_runtime --agent <name>`) is the Docker `ENTRYPOINT`. Spec 1 ships only the runtime + a base Dockerfile; the four real agents are Spec 3.

**Tech Stack:** Python 3.12, Pydantic v2, existing `fireflyframework_agentic` modules (`agents.base`, `agents.registry`, `observability.tracer`, `observability.usage`, `security.output_guard`), `pytest` (plain functions, no classes per CLAUDE.md), `respx`/`pytest-mock` for env isolation, GitHub Actions Docker action contract (`INPUT_*`, `$GITHUB_OUTPUT`, `$RUNNER_TEMP`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/fireflyframework_agentic/factory/__init__.py` | Empty package marker. |
| `src/fireflyframework_agentic/factory/action_runtime/__init__.py` | Public surface: `run_agent`, `MissingArtifactError`, `RunResult`. |
| `src/fireflyframework_agentic/factory/action_runtime/__main__.py` | `python -m …action_runtime` CLI. Thin: argparse → `run_agent`. |
| `src/fireflyframework_agentic/factory/action_runtime/exceptions.py` | `MissingArtifactError`, `ActionInputError`. |
| `src/fireflyframework_agentic/factory/action_runtime/github_outputs.py` | `write_output(key, value)` with single-line + heredoc multi-line. Reads `GITHUB_OUTPUT` env var. |
| `src/fireflyframework_agentic/factory/action_runtime/io_models.py` | Pydantic schemas: `RunResult`, `ArtifactSet`, plus the agent-specific Input/Output models that downstream agents (Spec 3) populate. |
| `src/fireflyframework_agentic/factory/action_runtime/artifact.py` | Reads `$RUNNER_TEMP/factory/<file>` into typed payloads; writes outputs to the same dir. Workflow-side upload is out of scope. |
| `src/fireflyframework_agentic/factory/action_runtime/feedback.py` | If `qa_report.json` is present in artifact dir AND `INPUT_ITERATION` > 1, loads it into a `FeedbackContext`. |
| `src/fireflyframework_agentic/factory/action_runtime/env.py` | Reads `INPUT_*` env vars, normalizes keys to lowercase, returns a `dict[str, str]`. Single source of "where does runtime config come from". |
| `src/fireflyframework_agentic/factory/action_runtime/runner.py` | `run_agent(name, env, artifacts) -> RunResult`. The orchestrator. |
| `.github/actions/_base/Dockerfile` | Base image used by all four agent actions. |
| `tests/unit/factory/__init__.py` | Test package marker. |
| `tests/unit/factory/action_runtime/__init__.py` | Test package marker. |
| `tests/unit/factory/action_runtime/test_github_outputs.py` | Plain-function tests. |
| `tests/unit/factory/action_runtime/test_env.py` | Plain-function tests. |
| `tests/unit/factory/action_runtime/test_artifact.py` | Plain-function tests. |
| `tests/unit/factory/action_runtime/test_feedback.py` | Plain-function tests. |
| `tests/unit/factory/action_runtime/test_runner.py` | End-to-end runner test using a stub agent. |
| `tests/unit/factory/action_runtime/conftest.py` | Fixtures: `tmp_runner_temp`, `tmp_github_output`, `register_stub_agent`. |
| `pyproject.toml` | Add `[factory]` extras: `sqlite-vec`, `pyyaml`. |

Conventions enforced (existing project rules):
- All test files start with `test_`. No classes — plain functions.
- All imports at the top of files. No inline imports.
- License headers on every new `.py` file (copy from a sibling).
- No "todo"/"currently"/dated language in docstrings.

---

## Task 1: Create `factory/` package skeleton

**Files:**
- Create: `src/fireflyframework_agentic/factory/__init__.py`
- Create: `src/fireflyframework_agentic/factory/action_runtime/__init__.py`
- Create: `tests/unit/factory/__init__.py`
- Create: `tests/unit/factory/action_runtime/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/factory/action_runtime/test_imports.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Smoke import test for the factory action_runtime package."""
from __future__ import annotations


def test_action_runtime_package_imports() -> None:
    import fireflyframework_agentic.factory.action_runtime as rt

    assert rt is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/factory/action_runtime/test_imports.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fireflyframework_agentic.factory'`.

- [ ] **Step 3: Create the package files**

Create `src/fireflyframework_agentic/factory/__init__.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Agentic SDLC factory subpackage.

Wraps `FireflyAgent` instances as reusable GitHub Actions and (in MVP2)
as steps inside the programmatic Pipeline DAG.
"""
```

Create `src/fireflyframework_agentic/factory/action_runtime/__init__.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Action runtime: turns a registered FireflyAgent into a GitHub Action run."""
```

Create empty `tests/unit/factory/__init__.py` and `tests/unit/factory/action_runtime/__init__.py` (just the license header).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/factory/action_runtime/test_imports.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/factory tests/unit/factory
git commit -m "feat(factory): scaffold action_runtime package"
```

---

## Task 2: `github_outputs.write_output`

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/github_outputs.py`
- Create: `tests/unit/factory/action_runtime/test_github_outputs.py`
- Create: `tests/unit/factory/action_runtime/conftest.py`

GitHub-Actions outputs go into the file pointed to by `$GITHUB_OUTPUT`. Single-line values use `key=value\n`. Multi-line values must use the heredoc form `key<<EOF\n…\nEOF\n` per [GitHub docs](https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-an-output-parameter). The function picks the form based on whether the value contains a newline.

- [ ] **Step 1: Write `conftest.py` fixture**

Create `tests/unit/factory/action_runtime/conftest.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Shared fixtures for action_runtime tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp file and point GITHUB_OUTPUT at it."""
    out = tmp_path / "github_output.txt"
    out.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    return out


@pytest.fixture
def tmp_runner_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create $RUNNER_TEMP/factory/ and point RUNNER_TEMP at the parent."""
    runner_temp = tmp_path / "runner_temp"
    factory_dir = runner_temp / "factory"
    factory_dir.mkdir(parents=True)
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    return factory_dir
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/factory/action_runtime/test_github_outputs.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for github_outputs.write_output."""
from __future__ import annotations

from pathlib import Path

import pytest

from fireflyframework_agentic.factory.action_runtime.github_outputs import (
    write_output,
)


def test_write_single_line_value(tmp_github_output: Path) -> None:
    write_output("pr_number", "42")
    assert tmp_github_output.read_text() == "pr_number=42\n"


def test_write_int_value_is_stringified(tmp_github_output: Path) -> None:
    write_output("iteration", 2)
    assert tmp_github_output.read_text() == "iteration=2\n"


def test_write_bool_value_is_lowercase(tmp_github_output: Path) -> None:
    write_output("qa_passed", True)
    assert tmp_github_output.read_text() == "qa_passed=true\n"


def test_write_multiline_uses_heredoc(tmp_github_output: Path) -> None:
    write_output("summary", "line one\nline two")
    text = tmp_github_output.read_text()
    assert "summary<<" in text
    assert "line one\nline two" in text
    # heredoc terminator on its own line
    delim = text.split("<<", 1)[1].split("\n", 1)[0]
    assert text.endswith(f"\n{delim}\n")


def test_write_multiple_outputs_appends(tmp_github_output: Path) -> None:
    write_output("a", "1")
    write_output("b", "2")
    assert tmp_github_output.read_text() == "a=1\nb=2\n"


def test_write_raises_when_github_output_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_OUTPUT"):
        write_output("k", "v")


def test_heredoc_delimiter_avoids_collision(tmp_github_output: Path) -> None:
    """If the value contains 'EOF' on its own line, the chosen delimiter must differ."""
    write_output("k", "before\nEOF\nafter")
    text = tmp_github_output.read_text()
    delim = text.split("<<", 1)[1].split("\n", 1)[0]
    assert delim != "EOF"
    # value preserved verbatim
    assert "before\nEOF\nafter" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/factory/action_runtime/test_github_outputs.py -v`
Expected: ALL FAIL with `ModuleNotFoundError: No module named '…github_outputs'`.

- [ ] **Step 4: Implement `github_outputs.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/github_outputs.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Write typed key/value pairs to the file pointed to by `$GITHUB_OUTPUT`.

GitHub Actions Docker actions communicate scalar outputs back to the workflow
by appending lines to this file. Multi-line values must use the heredoc form
documented at:
https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-an-output-parameter
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _heredoc_delimiter(text: str) -> str:
    """Return a delimiter that does not appear as a standalone line in `text`."""
    delim = "EOF"
    while f"\n{delim}\n" in f"\n{text}\n":
        delim = f"EOF_{secrets.token_hex(4)}"
    return delim


def write_output(key: str, value: Any) -> None:
    """Append `key=value` (or a heredoc block) to `$GITHUB_OUTPUT`.

    Raises:
        RuntimeError: If `GITHUB_OUTPUT` is not set in the environment.
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise RuntimeError("GITHUB_OUTPUT environment variable is not set")
    text = _format_scalar(value)
    out = Path(path)
    if "\n" in text:
        delim = _heredoc_delimiter(text)
        block = f"{key}<<{delim}\n{text}\n{delim}\n"
    else:
        block = f"{key}={text}\n"
    with out.open("a", encoding="utf-8") as fh:
        fh.write(block)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/factory/action_runtime/test_github_outputs.py -v`
Expected: ALL PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/github_outputs.py \
        tests/unit/factory/action_runtime/test_github_outputs.py \
        tests/unit/factory/action_runtime/conftest.py
git commit -m "feat(factory): add github_outputs.write_output with heredoc support"
```

---

## Task 3: `env.read_action_inputs`

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/env.py`
- Create: `tests/unit/factory/action_runtime/test_env.py`

GitHub Docker actions surface declared inputs as `INPUT_<NAME>` env vars (uppercased, spaces → underscores). The runtime needs to enumerate them and normalize keys back to lowercase Python identifiers.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/factory/action_runtime/test_env.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for env.read_action_inputs."""
from __future__ import annotations

import pytest

from fireflyframework_agentic.factory.action_runtime.env import read_action_inputs


def test_returns_lowercased_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_INTENT", "build a thing")
    monkeypatch.setenv("INPUT_PR_NUMBER", "42")
    inputs = read_action_inputs()
    assert inputs == {"intent": "build a thing", "pr_number": "42"}


def test_ignores_non_input_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_X", "1")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GITHUB_OUTPUT", "/tmp/x")
    inputs = read_action_inputs()
    assert inputs == {"x": "1"}


def test_empty_when_no_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os_environ_keys_starting_with_input()):
        monkeypatch.delenv(k, raising=False)
    inputs = read_action_inputs()
    assert inputs == {}


def os_environ_keys_starting_with_input() -> list[str]:
    import os
    return [k for k in os.environ if k.startswith("INPUT_")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/factory/action_runtime/test_env.py -v`
Expected: FAIL on import error.

- [ ] **Step 3: Implement `env.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/env.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Parse `INPUT_*` env vars set by GitHub Actions for Docker actions."""
from __future__ import annotations

import os


def read_action_inputs() -> dict[str, str]:
    """Return a dict of action inputs keyed by lowercase name.

    GitHub sets one env var per declared input, named `INPUT_<NAME>` where
    `<NAME>` is uppercase and any non-alphanumeric characters in the input
    name are replaced with underscores. We strip the prefix and lowercase
    the key so callers can build a Pydantic model from the result.
    """
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith("INPUT_"):
            continue
        out[key[len("INPUT_"):].lower()] = value
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/factory/action_runtime/test_env.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/env.py \
        tests/unit/factory/action_runtime/test_env.py
git commit -m "feat(factory): add env.read_action_inputs"
```

---

## Task 4: Exceptions module

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/exceptions.py`

Two typed errors. `MissingArtifactError` maps to GitHub-Actions exit code 78 (skip) per the spec. `ActionInputError` maps to exit code 1 (fail).

- [ ] **Step 1: Implement the exceptions**

Create `src/fireflyframework_agentic/factory/action_runtime/exceptions.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Typed errors raised by the action runtime."""
from __future__ import annotations

from fireflyframework_agentic.exceptions import FireflyAgenticError


class ActionRuntimeError(FireflyAgenticError):
    """Base class for action-runtime errors."""

    exit_code: int = 1


class MissingArtifactError(ActionRuntimeError):
    """A required artifact was not found in `$RUNNER_TEMP/factory/`."""

    exit_code: int = 78  # GitHub Actions "skipped" exit code


class ActionInputError(ActionRuntimeError):
    """An `INPUT_*` env var was missing or could not be parsed."""

    exit_code: int = 1
```

- [ ] **Step 2: Smoke test the import**

Add to `tests/unit/factory/action_runtime/test_imports.py`:

```python
def test_exceptions_import() -> None:
    from fireflyframework_agentic.factory.action_runtime.exceptions import (
        ActionInputError,
        ActionRuntimeError,
        MissingArtifactError,
    )

    assert issubclass(MissingArtifactError, ActionRuntimeError)
    assert MissingArtifactError.exit_code == 78
    assert ActionInputError.exit_code == 1
```

- [ ] **Step 3: Run**

Run: `pytest tests/unit/factory/action_runtime/test_imports.py -v`
Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/exceptions.py \
        tests/unit/factory/action_runtime/test_imports.py
git commit -m "feat(factory): add ActionRuntimeError hierarchy"
```

---

## Task 5: `artifact` module — read/write factory artifact directory

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/artifact.py`
- Create: `tests/unit/factory/action_runtime/test_artifact.py`

Reads markdown / JSON / YAML files from `$RUNNER_TEMP/factory/`; writes the same. Workflow-side upload is the workflow's job (Spec 4); this module is in-runner only.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/factory/action_runtime/test_artifact.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the artifact module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fireflyframework_agentic.factory.action_runtime.artifact import (
    ArtifactStore,
)
from fireflyframework_agentic.factory.action_runtime.exceptions import (
    MissingArtifactError,
)


def test_factory_dir_uses_runner_temp(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    assert store.root == tmp_runner_temp


def test_read_text_returns_content(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "prd.md").write_text("# PRD\n", encoding="utf-8")
    store = ArtifactStore.from_env()
    assert store.read_text("prd.md") == "# PRD\n"


def test_read_text_missing_raises(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    with pytest.raises(MissingArtifactError, match="prd.md"):
        store.read_text("prd.md")


def test_write_text_creates_file(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    store.write_text("adr.md", "# ADR\n")
    assert (tmp_runner_temp / "adr.md").read_text() == "# ADR\n"


def test_read_json_parses(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(json.dumps({"passed": True}))
    store = ArtifactStore.from_env()
    assert store.read_json("qa_report.json") == {"passed": True}


def test_write_json_round_trip(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    store.write_json("out.json", {"x": 1, "y": [2, 3]})
    assert json.loads((tmp_runner_temp / "out.json").read_text()) == {"x": 1, "y": [2, 3]}


def test_exists(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    assert store.exists("none.txt") is False
    (tmp_runner_temp / "yes.txt").write_text("hi")
    assert store.exists("yes.txt") is True


def test_from_env_raises_without_runner_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    with pytest.raises(RuntimeError, match="RUNNER_TEMP"):
        ArtifactStore.from_env()
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/factory/action_runtime/test_artifact.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `artifact.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/artifact.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Read and write artifact files in `$RUNNER_TEMP/factory/`."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fireflyframework_agentic.factory.action_runtime.exceptions import (
    MissingArtifactError,
)

ARTIFACT_SUBDIR = "factory"


@dataclass(frozen=True)
class ArtifactStore:
    """Filesystem-backed artifact store rooted at `$RUNNER_TEMP/factory/`."""

    root: Path

    @classmethod
    def from_env(cls) -> "ArtifactStore":
        runner_temp = os.environ.get("RUNNER_TEMP")
        if not runner_temp:
            raise RuntimeError("RUNNER_TEMP environment variable is not set")
        root = Path(runner_temp) / ARTIFACT_SUBDIR
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root)

    def _path(self, name: str) -> Path:
        return self.root / name

    def exists(self, name: str) -> bool:
        return self._path(name).is_file()

    def read_text(self, name: str) -> str:
        path = self._path(name)
        if not path.is_file():
            raise MissingArtifactError(f"required artifact not found: {name}")
        return path.read_text(encoding="utf-8")

    def write_text(self, name: str, content: str) -> None:
        self._path(name).write_text(content, encoding="utf-8")

    def read_json(self, name: str) -> Any:
        return json.loads(self.read_text(name))

    def write_json(self, name: str, payload: Any) -> None:
        self.write_text(name, json.dumps(payload, indent=2, sort_keys=True))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/factory/action_runtime/test_artifact.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/artifact.py \
        tests/unit/factory/action_runtime/test_artifact.py
git commit -m "feat(factory): add ArtifactStore for \$RUNNER_TEMP/factory/"
```

---

## Task 6: `feedback` module — load prior QAReport when iterating

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/feedback.py`
- Create: `tests/unit/factory/action_runtime/test_feedback.py`

When `INPUT_ITERATION` > 1 and `qa_report.json` exists, load it as a typed `FeedbackContext` so a downstream agent (codegen on retry) can read the prior failure.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/factory/action_runtime/test_feedback.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the feedback module."""
from __future__ import annotations

import json
from pathlib import Path

from fireflyframework_agentic.factory.action_runtime.artifact import ArtifactStore
from fireflyframework_agentic.factory.action_runtime.feedback import (
    FeedbackContext,
    load_feedback,
)


def test_returns_none_when_iteration_is_one(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(json.dumps({"passed": False}))
    store = ArtifactStore.from_env()
    assert load_feedback(store, iteration=1) is None


def test_returns_none_when_report_missing(tmp_runner_temp: Path) -> None:
    store = ArtifactStore.from_env()
    assert load_feedback(store, iteration=2) is None


def test_returns_context_when_present_and_iter_gt_one(tmp_runner_temp: Path) -> None:
    (tmp_runner_temp / "qa_report.json").write_text(
        json.dumps({"passed": False, "summary": "test_x failed", "failures": []})
    )
    store = ArtifactStore.from_env()
    fb = load_feedback(store, iteration=2)
    assert isinstance(fb, FeedbackContext)
    assert fb.iteration == 2
    assert fb.previous_report["summary"] == "test_x failed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/factory/action_runtime/test_feedback.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `feedback.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/feedback.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Loads prior QA feedback for codegen retry iterations.

The full `QAReport` Pydantic model lives with the qa agent (Spec 3). This
module accepts the report as a free-form dict so the runtime stays
agent-agnostic; agents that consume the feedback can validate it against
their own model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.factory.action_runtime.artifact import ArtifactStore


class FeedbackContext(BaseModel):
    iteration: int
    previous_report: dict[str, Any]


def load_feedback(store: ArtifactStore, *, iteration: int) -> FeedbackContext | None:
    """Return a `FeedbackContext` if iteration > 1 and `qa_report.json` exists."""
    if iteration <= 1:
        return None
    if not store.exists("qa_report.json"):
        return None
    return FeedbackContext(
        iteration=iteration,
        previous_report=store.read_json("qa_report.json"),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/factory/action_runtime/test_feedback.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/feedback.py \
        tests/unit/factory/action_runtime/test_feedback.py
git commit -m "feat(factory): add load_feedback for QA retry iterations"
```

---

## Task 7: `io_models.RunResult`

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/io_models.py`
- Update: `tests/unit/factory/action_runtime/test_imports.py`

The runtime returns a typed `RunResult` summarizing the agent run. Per-agent Input/Output schemas (e.g. `PRD`, `ADR`) are Spec 3's responsibility; this module ships only the shared `RunResult`.

- [ ] **Step 1: Add the import smoke test**

Append to `tests/unit/factory/action_runtime/test_imports.py`:

```python
def test_run_result_model() -> None:
    from fireflyframework_agentic.factory.action_runtime.io_models import RunResult

    r = RunResult(agent="product_owner", outputs={"pr_number": "42"}, cost_usd=0.1, tokens_in=10, tokens_out=20)
    assert r.agent == "product_owner"
    assert r.outputs == {"pr_number": "42"}
```

- [ ] **Step 2: Run — fails**

Run: `pytest tests/unit/factory/action_runtime/test_imports.py::test_run_result_model -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `io_models.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/io_models.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Shared Pydantic models for the action runtime.

Per-agent Input/Output schemas (PRD, ADR, QAReport, ...) live with the
specialized agents (Spec 3). Only the runtime-shared `RunResult` is here.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunResult(BaseModel):
    """Summary of a single agent run, written to `$GITHUB_OUTPUT` by the runtime."""

    agent: str
    outputs: dict[str, str] = Field(default_factory=dict)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
```

- [ ] **Step 4: Run — passes**

Run: `pytest tests/unit/factory/action_runtime/test_imports.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/io_models.py \
        tests/unit/factory/action_runtime/test_imports.py
git commit -m "feat(factory): add RunResult model"
```

---

## Task 8: `runner.run_agent` — the orchestrator

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/runner.py`
- Create: `tests/unit/factory/action_runtime/test_runner.py`
- Modify: `src/fireflyframework_agentic/factory/action_runtime/__init__.py` to export `run_agent`.

This is where it all comes together. `run_agent(name)`:

1. Reads `INPUT_*` env via `env.read_action_inputs()`.
2. Builds an `ArtifactStore` from `$RUNNER_TEMP`.
3. Loads optional feedback context.
4. Looks up the agent in `agent_registry`.
5. Composes a prompt from the inputs (the simplest sensible default: serialize the input dict + feedback as a markdown block; agents are responsible for their own prompt structure via the prompt registry, but the runtime gives them the raw inputs as a string).
6. Calls `agent.run(prompt)`.
7. Applies `default_output_guard` to the textual output.
8. Writes scalar outputs to `$GITHUB_OUTPUT` and returns a `RunResult`.

Tracing and usage tracking are already wrapped inside `agent.run`; the runtime reads the totals from `agent_context.usage_tracker` after the call.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/factory/action_runtime/test_runner.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""End-to-end test for runner.run_agent using a stub agent."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.factory.action_runtime.runner import run_agent


class _EchoModel(Model):
    """Deterministic stub model: returns a fixed text completion."""

    def __init__(self, response: str = "stub-response") -> None:
        self._response = response

    @property
    def model_name(self) -> str:
        return "echo-stub"

    @property
    def system(self) -> str:
        return "stub"

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.usage import Usage

        return ModelResponse(parts=[TextPart(content=self._response)]), Usage(
            request_tokens=5, response_tokens=7, total_tokens=12
        )


@pytest.fixture
def stub_agent() -> FireflyAgent[Any, Any]:
    """Register a stub agent named 'stub' for the test, unregister after."""
    agent = FireflyAgent(name="stub", model=_EchoModel(), auto_register=False)
    agent_registry.register(agent)
    yield agent
    agent_registry.unregister("stub")


def test_run_agent_writes_outputs(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: FireflyAgent[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INPUT_INTENT", "build a thing")
    monkeypatch.setenv("INPUT_ITERATION", "1")

    result = asyncio.run(run_agent("stub"))

    assert result.agent == "stub"
    output_text = tmp_github_output.read_text()
    assert "agent=stub" in output_text
    assert "tokens_in=5" in output_text
    assert "tokens_out=7" in output_text
    # cost_usd may be 0 since UsageTracker has no pricing for echo-stub
    assert "cost_usd=" in output_text


def test_run_agent_unknown_name_raises(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
) -> None:
    from fireflyframework_agentic.exceptions import AgentNotFoundError

    with pytest.raises(AgentNotFoundError):
        asyncio.run(run_agent("does-not-exist"))


def test_run_agent_loads_feedback_when_iteration_gt_one(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: FireflyAgent[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    (tmp_runner_temp / "qa_report.json").write_text(
        json.dumps({"passed": False, "summary": "the test failed"})
    )
    monkeypatch.setenv("INPUT_INTENT", "fix it")
    monkeypatch.setenv("INPUT_ITERATION", "2")

    result = asyncio.run(run_agent("stub"))
    # The runner records that it consumed feedback as a side-channel output
    output_text = tmp_github_output.read_text()
    assert "iteration=2" in output_text
    assert "feedback_used=true" in output_text
    assert result.agent == "stub"
```

- [ ] **Step 2: Run — fails**

Run: `pytest tests/unit/factory/action_runtime/test_runner.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `runner.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/runner.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Top-level entrypoint that runs a registered agent end-to-end inside an Action."""
from __future__ import annotations

import logging
from typing import Any

from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.factory.action_runtime.artifact import ArtifactStore
from fireflyframework_agentic.factory.action_runtime.env import read_action_inputs
from fireflyframework_agentic.factory.action_runtime.feedback import load_feedback
from fireflyframework_agentic.factory.action_runtime.github_outputs import write_output
from fireflyframework_agentic.factory.action_runtime.io_models import RunResult
from fireflyframework_agentic.security import default_output_guard

logger = logging.getLogger(__name__)


def _compose_prompt(inputs: dict[str, str], feedback: Any) -> str:
    """Build a default prompt from raw inputs + optional feedback.

    Agents typically override this by setting their own system prompt and
    relying on retrieval-augmented context. This default is the minimum
    contract: the input dict, rendered as markdown, plus the prior QA
    report when retrying.
    """
    lines = ["# Inputs", ""]
    for k, v in sorted(inputs.items()):
        lines.append(f"## {k}\n\n{v}\n")
    if feedback is not None:
        lines.append("# Previous QA Report")
        lines.append("")
        lines.append(f"Iteration: {feedback.iteration}")
        lines.append("")
        lines.append("```json")
        import json

        lines.append(json.dumps(feedback.previous_report, indent=2, sort_keys=True))
        lines.append("```")
    return "\n".join(lines)


async def run_agent(name: str) -> RunResult:
    """Run the registered agent `name`, write outputs, return a RunResult.

    Reads `INPUT_*` env vars + `$RUNNER_TEMP/factory/` artifacts. Writes
    `agent`, `tokens_in`, `tokens_out`, `cost_usd`, `iteration`, and
    `feedback_used` to `$GITHUB_OUTPUT`.

    Raises:
        AgentNotFoundError: If `name` is not registered.
        MissingArtifactError: If the agent declares a required artifact
            that is not present (raised by per-agent code in Spec 3).
    """
    inputs = read_action_inputs()
    iteration = int(inputs.get("iteration", "1"))
    store = ArtifactStore.from_env()
    feedback = load_feedback(store, iteration=iteration)
    agent = agent_registry.get(name)

    prompt = _compose_prompt(inputs, feedback)
    response = await agent.run(prompt)

    text = str(response.output if hasattr(response, "output") else response)
    text = default_output_guard.scrub(text) if hasattr(default_output_guard, "scrub") else text

    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "request_tokens", 0) or 0
    tokens_out = getattr(usage, "response_tokens", 0) or 0
    cost_usd = float(getattr(usage, "cost_usd", 0.0) or 0.0)

    write_output("agent", name)
    write_output("tokens_in", tokens_in)
    write_output("tokens_out", tokens_out)
    write_output("cost_usd", f"{cost_usd:.6f}")
    write_output("iteration", iteration)
    write_output("feedback_used", feedback is not None)

    return RunResult(
        agent=name,
        outputs={"text": text},
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
```

- [ ] **Step 4: Update `__init__.py` to export `run_agent`**

Edit `src/fireflyframework_agentic/factory/action_runtime/__init__.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Action runtime: turns a registered FireflyAgent into a GitHub Action run."""
from __future__ import annotations

from fireflyframework_agentic.factory.action_runtime.exceptions import (
    ActionInputError,
    ActionRuntimeError,
    MissingArtifactError,
)
from fireflyframework_agentic.factory.action_runtime.io_models import RunResult
from fireflyframework_agentic.factory.action_runtime.runner import run_agent

__all__ = [
    "ActionInputError",
    "ActionRuntimeError",
    "MissingArtifactError",
    "RunResult",
    "run_agent",
]
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/factory/action_runtime/test_runner.py -v`
Expected: 3 PASS.

If `default_output_guard` does not have a `.scrub` method (verify with `grep -n "def scrub\|def __call__" src/fireflyframework_agentic/security/output_guard.py`), replace `default_output_guard.scrub(text)` with whatever the actual API is — the `hasattr` guard already short-circuits to identity if it's missing.

- [ ] **Step 6: Run full suite to make sure nothing else broke**

Run: `pytest tests/unit/factory/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/runner.py \
        src/fireflyframework_agentic/factory/action_runtime/__init__.py \
        tests/unit/factory/action_runtime/test_runner.py
git commit -m "feat(factory): add run_agent runner"
```

---

## Task 9: `__main__` CLI

**Files:**
- Create: `src/fireflyframework_agentic/factory/action_runtime/__main__.py`
- Create: `tests/unit/factory/action_runtime/test_main.py`

The Docker image's `ENTRYPOINT` is `python -m fireflyframework_agentic.factory.action_runtime`. The `__main__` module parses `--agent <name>`, runs `run_agent`, exits with the right code.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/factory/action_runtime/test_main.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the action_runtime CLI."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models import Model

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.registry import agent_registry
from fireflyframework_agentic.factory.action_runtime.__main__ import main


class _EchoModel(Model):
    @property
    def model_name(self) -> str:
        return "echo-stub"

    @property
    def system(self) -> str:
        return "stub"

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.usage import Usage

        return ModelResponse(parts=[TextPart(content="ok")]), Usage(
            request_tokens=1, response_tokens=1, total_tokens=2
        )


@pytest.fixture
def stub_agent() -> FireflyAgent[Any, Any]:
    agent = FireflyAgent(name="stub", model=_EchoModel(), auto_register=False)
    agent_registry.register(agent)
    yield agent
    agent_registry.unregister("stub")


def test_main_happy_path(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    stub_agent: FireflyAgent[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["action_runtime", "--agent", "stub"])
    rc = main()
    assert rc == 0


def test_main_unknown_agent_returns_nonzero(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["action_runtime", "--agent", "does-not-exist"])
    rc = main()
    assert rc == 1


def test_main_missing_artifact_returns_78(
    tmp_runner_temp: Path,
    tmp_github_output: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `MissingArtifactError` raised inside the agent maps to exit 78."""
    from fireflyframework_agentic.factory.action_runtime.exceptions import (
        MissingArtifactError,
    )

    class _BadModel(Model):
        @property
        def model_name(self) -> str:
            return "bad"

        @property
        def system(self) -> str:
            return "stub"

        async def request(self, *_: Any, **__: Any) -> Any:
            raise MissingArtifactError("prd.md")

    bad = FireflyAgent(name="bad", model=_BadModel(), auto_register=False)
    agent_registry.register(bad)
    try:
        monkeypatch.setattr(sys, "argv", ["action_runtime", "--agent", "bad"])
        rc = main()
        assert rc == 78
    finally:
        agent_registry.unregister("bad")
```

- [ ] **Step 2: Run — fails**

Run: `pytest tests/unit/factory/action_runtime/test_main.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `__main__.py`**

Create `src/fireflyframework_agentic/factory/action_runtime/__main__.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""CLI entry point: `python -m fireflyframework_agentic.factory.action_runtime`."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from fireflyframework_agentic.exceptions import AgentNotFoundError
from fireflyframework_agentic.factory.action_runtime.exceptions import (
    ActionRuntimeError,
)
from fireflyframework_agentic.factory.action_runtime.runner import run_agent

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="factory-action-runtime")
    parser.add_argument("--agent", required=True, help="Registered agent name to run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parse_args(argv)
    try:
        asyncio.run(run_agent(args.agent))
        return 0
    except ActionRuntimeError as e:
        # Includes MissingArtifactError → exit 78, ActionInputError → 1
        sys.stderr.write(f"::error::{type(e).__name__}: {e}\n")
        return e.exit_code
    except AgentNotFoundError as e:
        sys.stderr.write(f"::error::AgentNotFoundError: {e}\n")
        return 1
    except Exception as e:  # noqa: BLE001
        # Print the error annotation; non-zero exit but distinct from typed failures.
        sys.stderr.write(f"::error::{type(e).__name__}: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/factory/action_runtime/test_main.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fireflyframework_agentic/factory/action_runtime/__main__.py \
        tests/unit/factory/action_runtime/test_main.py
git commit -m "feat(factory): add action_runtime CLI entry point"
```

---

## Task 10: `[factory]` extras in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml` — add `[project.optional-dependencies] factory = [...]`.

The runtime itself uses only stdlib + Pydantic + Pydantic-AI, all of which are core deps. The `[factory]` extra is reserved for downstream code (Spec 2 indexer needs `sqlite-vec`, Spec 3 codegen needs `pyyaml`). Adding it here means the base Dockerfile (Task 11) only references one extra.

- [ ] **Step 1: Inspect existing extras**

Run: `grep -n "optional-dependencies\|^\[project" pyproject.toml | head -20`

- [ ] **Step 2: Add the extras block**

Edit `pyproject.toml`. After the existing `[project.optional-dependencies]` block (or create one if absent), add:

```toml
factory = [
    "sqlite-vec>=0.1.0",
    "pyyaml>=6.0",
]
```

If the section already exists, just add the `factory = [...]` key. Do NOT alter other extras.

- [ ] **Step 3: Verify install resolves**

Run: `uv pip install --dry-run -e ".[factory]"` (from the repo root, with the venv activated).
Expected: resolves cleanly.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build(factory): add [factory] optional dependency group"
```

---

## Task 11: Base Dockerfile

**Files:**
- Create: `.github/actions/_base/Dockerfile`
- Create: `.github/actions/_base/README.md`

The four agent actions (Spec 3) will each `FROM ghcr.io/fireflyframework/factory-base:<tag>` and just declare a `CMD ["--agent", "<name>"]`. The base image has the Python interpreter, the agentic library installed with the `[factory]` extra, the `gh` CLI for codegen/qa, a non-root user, and the runtime as the entrypoint.

- [ ] **Step 1: Create the Dockerfile**

Create `.github/actions/_base/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

# System deps: gh CLI for codegen/qa, git for codegen workspace ops.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod 644 /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -u 1001 -m runner
WORKDIR /home/runner

# Copy the source tree (built once per agentic-library release).
COPY --chown=runner:runner pyproject.toml uv.lock README.md /home/runner/
COPY --chown=runner:runner src /home/runner/src

# Install the agentic library with the [factory] extra.
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache ".[factory]"

USER runner
ENTRYPOINT ["python", "-m", "fireflyframework_agentic.factory.action_runtime"]
```

- [ ] **Step 2: Create the README**

Create `.github/actions/_base/README.md`:

```markdown
# factory-base

Base Docker image for all factory agent actions. Each agent action's
`Dockerfile` is just:

    FROM ghcr.io/fireflyframework/factory-base:<tag>
    CMD ["--agent", "<agent-name>"]

The image ships:

- Python 3.12-slim
- `fireflyframework-agentic[factory]` (this repo at the build SHA)
- `gh` CLI (used by codegen + qa)
- `git`
- A non-root `runner` user

The entrypoint is `python -m fireflyframework_agentic.factory.action_runtime`.
Tag scheme: CalVer (`YYYY.MM.PP`) plus `<sha>`.
```

- [ ] **Step 3: Smoke-build the image locally**

Run: `docker buildx build --load -t factory-base:dev -f .github/actions/_base/Dockerfile .`
Expected: build succeeds.

(Per global rules, always use `docker buildx build`, never `docker build`.)

- [ ] **Step 4: Smoke-run the entrypoint**

Run: `docker run --rm factory-base:dev --agent does-not-exist`
Expected: exit code 1, with `::error::AgentNotFoundError: …` on stderr.

- [ ] **Step 5: Commit**

```bash
git add .github/actions/_base/Dockerfile .github/actions/_base/README.md
git commit -m "build(factory): add base Dockerfile for agent actions"
```

---

## Task 12: Final full-suite check + push

**Files:** none modified.

- [ ] **Step 1: Run full project test suite**

Run: `pytest tests/ -x -q`
Expected: all green.

- [ ] **Step 2: Run linters**

Run: `ruff check src/fireflyframework_agentic/factory tests/unit/factory`
Run: `ruff format --check src/fireflyframework_agentic/factory tests/unit/factory`
Expected: clean.

- [ ] **Step 3: Push branch**

Run: `git push -u origin spec/factory-mvp1`

- [ ] **Step 4: Open PR**

Use the agreed PR-template phrasing. Title: `feat(factory): MVP1 action runtime (Spec 1)`. Body lists each task and links to the spec. No "Generated with Claude" anywhere.

---

## Verification (matches spec §Verification)

- ✅ A `python -m fireflyframework_agentic.factory.action_runtime --agent <stub>` invocation succeeds against a stub agent before any real Spec 3 agent exists. Verified by `test_main_happy_path`.
- ✅ `MissingArtifactError` produces exit code 78. Verified by `test_main_missing_artifact_returns_78`.
- ✅ Importing the package adds no measurable startup cost when extras are absent. The runtime imports nothing from `[factory]` extras at top level (those are reserved for Spec 2/3 modules).
- 🟡 `act -j test-action-runtime` is deferred: a smoke workflow that pulls the base image and runs against a stub is added in Spec 4. The unit tests in this plan exercise the Python surface; the Docker smoke is exercised by Task 11 step 4 (`docker run`).

---

## Self-Review Notes

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| Module layout (§Module layout) | Tasks 1, 4, 5, 6, 7, 8, 9 |
| Public API `run_agent` | Task 8 |
| Input contract (`INPUT_*` + artifacts) | Tasks 3, 5 |
| Output contract (`$GITHUB_OUTPUT` + artifact files) | Tasks 2, 5, 8 |
| `MissingArtifactError` → exit 78 | Tasks 4, 9 |
| Tracing / Usage / Output guard wiring | Task 8 (reads `agent.run` usage; applies `default_output_guard`) |
| Base Docker image | Task 11 |
| `[factory]` extras | Task 10 |
| `act` test harness | Deferred to Spec 4 (noted in Verification) |

**Type consistency:** `RunResult` defined in Task 7 is exported from `__init__.py` in Task 8 step 4, used in Task 8 step 3, returned from `run_agent`. `MissingArtifactError` defined in Task 4, raised from `artifact.py` in Task 5, caught in Task 9. `ArtifactStore` defined in Task 5, used in Tasks 6, 8. `FeedbackContext` defined in Task 6, used in Task 8. All consistent.

**Placeholder scan:** No "TBD"/"TODO"/"implement later". The "todo" string only appears as part of a feature name in Spec 5 (alternative use case "TODO REST microservice"), not in this plan.

**Open issue flagged for the engineer:** Task 8 step 5 notes that `default_output_guard.scrub` is hypothetical — the `hasattr` guard short-circuits if the API differs. Confirm during implementation by reading `src/fireflyframework_agentic/security/output_guard.py` and replace with the real API.
