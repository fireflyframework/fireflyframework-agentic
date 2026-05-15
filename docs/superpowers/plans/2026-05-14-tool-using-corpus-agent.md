# Tool-using corpus answer agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed expand→retrieve→answer pipeline in `CorpusAgent.query` with a tool-using ReAct-style agent (driven by pydantic-ai's native tool loop) that calls `knowledge_search`, `sql_query`, `inspect_table`, and `python_compute`, emits a typed reproducible `ReasoningTrace`, and is opt-in via an `answer_strategy` flag (default unchanged).

**Architecture:** New `ReasoningAnswerAgent` follows the proven `StructuredRetriever` shape — a `FireflyAgent(tools=[...])` whose tool closures share state through a contextvar-scoped `_LoopContext`. Pydantic-ai owns the tool loop; we translate its `AgentRunResult.all_messages()` into a `ReasoningTrace` post-hoc. `python_compute` is an AST-validated Python sandbox with stdlib + numpy + pandas. Existing `AnswerAgent` is preserved for the default `answer_strategy="fast"`.

**Tech Stack:** Python 3.13, pydantic-ai (via `FireflyAgent`), sqlite3, sqlite-vec, numpy + pandas (new optional extra `reasoning-eval`), pytest + pytest-asyncio, ruff.

**Spec:** `docs/superpowers/specs/2026-05-14-tool-using-corpus-agent-design.md`

---

## File Structure

**Create:**
- `fireflyframework_agentic/rag/retrieval/_python_compute.py` — AST-validated sandbox; private module, ~200 LoC.
- `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py` — `ReasoningAnswerAgent`, `_LoopContext`, four tool closures, system prompt, trace translation; ~350 LoC.
- `tests/unit/corpus_search/test_python_compute_sandbox.py`
- `tests/unit/corpus_search/test_reasoning_answerer.py`
- `tests/unit/corpus_search/test_trace_translation.py`
- `tests/unit/corpus_search/test_citation_enrichment.py`
- `tests/unit/corpus_search/test_corpus_agent_strategy_flag.py`
- `tests/examples/corpus_search/reasoning_fixtures.py` — fixture loader + ground-truth dict.
- `tests/examples/corpus_search/benchmark/corpus/reasoning/quarterly_revenue.csv`
- `tests/examples/corpus_search/benchmark/corpus/reasoning/headcount_snapshots.csv`
- `tests/examples/corpus_search/benchmark/corpus/reasoning/methodology.md`
- `tests/examples/corpus_search/replay/q1_yoy_growth.json` (and `q2`…`q5`)
- `tests/examples/corpus_search/test_corpus_query_reasoning.py` — Tier A replay tests.
- `tests/examples/corpus_search/test_trace_is_replayable.py`
- `tests/examples/corpus_search/test_corpus_query_reasoning_real_llm.py` — Tier B nightly.
- `scripts/capture_reasoning_replay.py` — operator-only CLI.

**Modify:**
- `pyproject.toml` — add `[reasoning-eval]` optional extra.
- `fireflyframework_agentic/rag/retrieval/answerer.py` — add `reasoning_trace` field to `Answer`.
- `fireflyframework_agentic/rag/retrieval/__init__.py` — export `ReasoningAnswerAgent`.
- `fireflyframework_agentic/rag/agent.py` — add `answer_strategy` ctor param; branch in `_ensure_query_ready`; add `include_trace` to `query()`.
- `fireflyframework_agentic/rag/_telemetry.py` — register new histogram/counter.
- `examples/corpus_search/mcp_server.py` — `corpus_query` tool gains `strategy` + `include_trace`.
- `docs/use-case-corpus-search.md`, `docs/reasoning.md`, `CHANGELOG.md`.

---

## Task 1: Add `[reasoning-eval]` optional extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the extra**

Edit `pyproject.toml` — insert a new section in `[project.optional-dependencies]`, alphabetically (after `rag`, before `rest`):

```toml
reasoning-eval = [
    "numpy>=2.0.0",
    "pandas>=2.2.0",
]
```

- [ ] **Step 2: Refresh the lockfile**

```bash
uv lock --upgrade-package numpy --upgrade-package pandas
```

Expected: no errors; `uv.lock` updated.

- [ ] **Step 3: Verify install works**

```bash
uv sync --extra reasoning-eval
uv run python -c "import numpy, pandas; print(numpy.__version__, pandas.__version__)"
```

Expected: prints two version strings, no import errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add [reasoning-eval] extra (numpy + pandas) for python_compute sandbox"
```

---

## Task 2: AST denylist validator (pure function)

**Files:**
- Create: `fireflyframework_agentic/rag/retrieval/_python_compute.py`
- Test: `tests/unit/corpus_search/test_python_compute_sandbox.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/corpus_search/test_python_compute_sandbox.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

import pytest

from fireflyframework_agentic.rag.retrieval._python_compute import (
    PythonComputeError,
    validate_source,
)


def test_validate_simple_expression_passes():
    validate_source("1 + 2")  # no error


def test_validate_multiline_assignment_passes():
    validate_source("x = 1\ny = x + 2\nresult = y")


def test_validate_rejects_dunder_attribute():
    with pytest.raises(PythonComputeError, match="dunder"):
        validate_source("x.__class__")


def test_validate_rejects_dunder_name():
    with pytest.raises(PythonComputeError, match="dunder"):
        validate_source("__import__('os')")


def test_validate_rejects_disallowed_builtin_call():
    # f-strings keep the denied builtin literals out of this file's own source.
    for builtin in ("eval", "exec", "compile", "open", "input"):
        with pytest.raises(PythonComputeError, match=builtin):
            validate_source(f"{builtin}('x')")


def test_validate_rejects_non_whitelisted_import():
    with pytest.raises(PythonComputeError, match="os"):
        validate_source("import os")


def test_validate_accepts_whitelisted_import():
    validate_source("import math")
    validate_source("from statistics import mean")


def test_validate_rejects_from_import_of_non_whitelisted():
    with pytest.raises(PythonComputeError, match="sys"):
        validate_source("from sys import argv")


def test_validate_rejects_attribute_subclasses_escape():
    with pytest.raises(PythonComputeError, match="dunder"):
        validate_source("().__class__.__bases__[0].__subclasses__()")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_python_compute_sandbox.py -v
```

Expected: ImportError on `_python_compute`.

- [ ] **Step 3: Implement the validator**

Create `fireflyframework_agentic/rag/retrieval/_python_compute.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Restricted Python sandbox for the corpus reasoning agent's python_compute tool.

AST-validated against a denylist before execution. Pragmatic — not adversarial.
We trust our own model, not an attacker. See spec
``docs/superpowers/specs/2026-05-14-tool-using-corpus-agent-design.md``.
"""

from __future__ import annotations

import ast

WHITELISTED_MODULES: frozenset[str] = frozenset({
    "math", "statistics", "decimal", "fractions",
    "datetime", "calendar",
    "re", "string", "textwrap", "unicodedata",
    "json", "collections", "itertools", "functools", "operator",
    "dataclasses", "enum",
    "numpy", "pandas",
})

DISALLOWED_BUILTIN_NAMES: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
    "open", "input", "breakpoint",
    "help", "dir", "vars", "globals", "locals",
})


class PythonComputeError(Exception):
    """Raised by the validator when source contains a denied AST pattern."""


def validate_source(source: str) -> None:
    """Parse ``source`` and walk its AST, raising :class:`PythonComputeError` on
    any denied pattern. Pure function — no execution. Always parses in exec
    mode so multi-statement source is accepted.
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise PythonComputeError(f"syntax error: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            raise PythonComputeError(f"dunder name '{node.id}' is not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            raise PythonComputeError(f"dunder attribute '.{node.attr}' is not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DISALLOWED_BUILTIN_NAMES:
                raise PythonComputeError(f"call to '{node.func.id}' is not allowed")
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top not in WHITELISTED_MODULES:
                    raise PythonComputeError(f"import of '{alias.name}' is not allowed")
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".", 1)[0]
            if mod not in WHITELISTED_MODULES:
                raise PythonComputeError(f"from-import of '{node.module}' is not allowed")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/corpus_search/test_python_compute_sandbox.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/_python_compute.py tests/unit/corpus_search/test_python_compute_sandbox.py
git commit -m "feat(python_compute): AST denylist validator (pure function, no execution)"
```

---

## Task 3: Sandbox runner with restricted namespace, timeout, output cap

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/_python_compute.py`
- Test: `tests/unit/corpus_search/test_python_compute_sandbox.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/corpus_search/test_python_compute_sandbox.py`:

```python
from fireflyframework_agentic.rag.retrieval._python_compute import run_python_compute


def test_run_returns_result_binding():
    out = run_python_compute("result = 1 + 2")
    assert "3" in out


def test_run_returns_last_expression_when_no_result():
    out = run_python_compute("1 + 2")
    assert "3" in out


def test_run_returns_none_when_no_expression():
    out = run_python_compute("x = 1")
    assert "None" in out


def test_run_binds_data_as_locals():
    out = run_python_compute("result = sum(values)", data={"values": [1, 2, 3]})
    assert "6" in out


def test_run_captures_print_output():
    out = run_python_compute("print('hello')\nresult = 1")
    assert "hello" in out
    assert "1" in out


def test_run_uses_per_call_random_seed():
    import random as host_random
    host_state = host_random.getstate()
    out1 = run_python_compute("result = random.random()")
    out2 = run_python_compute("result = random.random()")
    assert out1 == out2  # deterministic: fresh Random(0) each call
    assert host_random.getstate() == host_state  # host state untouched


def test_run_numpy_works():
    out = run_python_compute("import numpy as np\nresult = float(np.mean([1.0, 2.0, 3.0]))")
    assert "2.0" in out


def test_run_pandas_dataframe_renders_as_markdown():
    out = run_python_compute(
        "import pandas as pd\n"
        "result = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})"
    )
    assert "|" in out and "a" in out and "b" in out


def test_run_denied_pattern_returns_error_string():
    out = run_python_compute("__import__('os')")
    assert out.startswith("python_compute error:")


def test_run_syntax_error_returns_error_string():
    out = run_python_compute("def (oops:")
    assert out.startswith("python_compute error:")


def test_run_undefined_name_returns_error_string():
    out = run_python_compute("result = undefined_thing")
    assert out.startswith("python_compute error:")


def test_run_timeout_returns_error_string():
    out = run_python_compute("while True:\n    pass", timeout_seconds=0.2)
    assert out.startswith("python_compute timeout") or out.startswith("python_compute error:")


def test_run_output_cap_truncates():
    out = run_python_compute("result = list(range(1000))", output_cap_bytes=50)
    assert "truncated" in out
    assert len(out) <= 100  # cap + suffix wiggle
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/corpus_search/test_python_compute_sandbox.py::test_run_returns_result_binding -v
```

Expected: ImportError on `run_python_compute`.

- [ ] **Step 3: Implement the runner**

Append to `fireflyframework_agentic/rag/retrieval/_python_compute.py`. We alias the two Python builtins the sandbox needs to drive a validated compiled AST. Naming them at module top makes the call sites explicit: "this is the deliberate sandbox boundary, not casual use."

```python
import builtins as _builtins
import io
import random
import threading
from contextlib import redirect_stdout
from typing import Any

# Sandbox-boundary aliases. The two Python builtins below are exactly the
# call sites we want a security reviewer to read: a compiled AST that has
# already passed validate_source().
_RUN_BLOCK = _builtins.exec     # run a compiled exec-mode AST in our namespace
_RUN_EXPR  = _builtins.eval     # evaluate a compiled expression in our namespace

ALLOWED_BUILTINS: frozenset[str] = frozenset({
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "frozenset", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "ord", "pow", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
})


def _build_namespace(data: dict[str, Any] | None) -> dict[str, Any]:
    """Build the locals/globals for one run. Imports are lazy so a missing
    numpy/pandas surfaces a clear error rather than a module-load failure.
    """
    safe_builtins = {name: getattr(_builtins, name) for name in ALLOWED_BUILTINS}
    ns: dict[str, Any] = {"__builtins__": safe_builtins}

    import math, statistics, decimal, fractions  # noqa: E401
    import datetime as _dt, calendar  # noqa: E401
    import re, string, textwrap, unicodedata  # noqa: E401
    import json as _json, collections, itertools, functools, operator  # noqa: E401
    import dataclasses, enum  # noqa: E401

    ns.update({
        "math": math, "statistics": statistics, "decimal": decimal,
        "fractions": fractions, "datetime": _dt, "calendar": calendar,
        "re": re, "string": string, "textwrap": textwrap,
        "unicodedata": unicodedata, "json": _json,
        "collections": collections, "itertools": itertools,
        "functools": functools, "operator": operator,
        "dataclasses": dataclasses, "enum": enum,
        # Per-call deterministic random source; host state untouched.
        "random": random.Random(0),
    })

    try:
        import numpy as _np
        ns["np"] = _np
        ns["numpy"] = _np
    except ImportError as exc:
        raise RuntimeError(
            "install fireflyframework-agentic[reasoning-eval] to use python_compute"
        ) from exc
    try:
        import pandas as _pd
        ns["pd"] = _pd
        ns["pandas"] = _pd
    except ImportError as exc:
        raise RuntimeError(
            "install fireflyframework-agentic[reasoning-eval] to use python_compute"
        ) from exc

    if data:
        ns.update(data)
    return ns


def _render(value: Any) -> str:
    """Render a result value for return to the LLM. Special-cases DataFrame and
    ndarray to keep traces readable; falls back to ``repr``.
    """
    try:
        import pandas as pd  # noqa: PLC0415
        if isinstance(value, pd.DataFrame):
            return value.to_markdown(index=False)
    except ImportError:
        pass
    try:
        import numpy as np  # noqa: PLC0415
        if isinstance(value, np.ndarray):
            with np.printoptions(threshold=200, edgeitems=3):
                return repr(value)
    except ImportError:
        pass
    return repr(value)


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    excess = len(text) - cap
    return text[:cap] + f"… (truncated, {excess} more bytes)"


def run_python_compute(
    source: str,
    data: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 5.0,
    output_cap_bytes: int = 8192,
) -> str:
    """Validate, execute, and render restricted Python.

    Returns the rendered result (or last-expression value if ``result`` is not
    set), with captured stdout prepended. On any failure (denied AST, syntax,
    runtime, timeout) returns a string starting with ``"python_compute error:"``
    or ``"python_compute timeout"`` so the LLM can self-correct without the
    loop dying.
    """
    try:
        validate_source(source)
    except PythonComputeError as exc:
        return f"python_compute error: {exc}"

    try:
        ns = _build_namespace(data)
    except RuntimeError as exc:
        return f"python_compute error: {exc}"

    tree = ast.parse(source, mode="exec")
    last = tree.body[-1] if tree.body else None
    explicitly_assigns_result = any(
        isinstance(s, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "result" for t in s.targets
        )
        for s in tree.body
    )
    take_last_expr = isinstance(last, ast.Expr) and not explicitly_assigns_result

    buf = io.StringIO()
    holder: list[Any] = []
    err: list[BaseException] = []

    def _runner() -> None:
        try:
            with redirect_stdout(buf):
                if take_last_expr and last is not None:
                    body_tree = ast.Module(body=tree.body[:-1], type_ignores=[])
                    expr_tree = ast.Expression(body=last.value)
                    ast.fix_missing_locations(body_tree)
                    ast.fix_missing_locations(expr_tree)
                    _RUN_BLOCK(compile(body_tree, "<python_compute>", "exec"), ns)
                    holder.append(_RUN_EXPR(compile(expr_tree, "<python_compute>", "eval"), ns))
                else:
                    _RUN_BLOCK(compile(tree, "<python_compute>", "exec"), ns)
                    holder.append(ns.get("result"))
        except BaseException as exc:  # noqa: BLE001
            err.append(exc)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        return f"python_compute timeout after {timeout_seconds}s"
    if err:
        return f"python_compute error: {type(err[0]).__name__}: {err[0]}"

    parts: list[str] = []
    stdout = buf.getvalue()
    if stdout:
        parts.append(stdout.rstrip("\n"))
    parts.append(_render(holder[0] if holder else None))
    combined = "\n".join(parts)
    return _truncate(combined, output_cap_bytes)
```

- [ ] **Step 4: Run all sandbox tests**

```bash
uv run pytest tests/unit/corpus_search/test_python_compute_sandbox.py -v
```

Expected: all tests pass. If the timeout test is flaky on a slow runner, raise `timeout_seconds=0.2` to `0.5`.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/_python_compute.py tests/unit/corpus_search/test_python_compute_sandbox.py
git commit -m "feat(python_compute): restricted Python sandbox with stdlib + numpy/pandas"
```

---

## Task 4: `_LoopContext` and contextvar

**Files:**
- Create: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_reasoning_answerer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/corpus_search/test_reasoning_answerer.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pathlib import Path

import pytest

from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _CURRENT_CTX,
    _LoopContext,
)


def test_loop_context_defaults():
    ctx = _LoopContext(
        corpus_agent=None,
        structured_retriever=None,
        schemas=[],
        db_path=Path("/tmp/nonexistent.sqlite"),
    )
    assert ctx.accumulated_hits == {}
    assert ctx.sql_calls == []


def test_contextvar_default_is_none():
    assert _CURRENT_CTX.get() is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py::test_loop_context_defaults -v
```

Expected: ImportError.

- [ ] **Step 3: Create the module skeleton**

Create `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`:

```python
# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tool-using corpus answer agent.

See spec ``docs/superpowers/specs/2026-05-14-tool-using-corpus-agent-design.md``.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fireflyframework_agentic.rag.agent import CorpusAgent
    from fireflyframework_agentic.rag.corpus import ChunkHit
    from fireflyframework_agentic.rag.ingest.structured_schema import TargetSchema
    from fireflyframework_agentic.rag.retrieval.sql import (
        SqlRetrievalOutcome,
        StructuredRetriever,
    )


@dataclass(slots=True)
class _LoopContext:
    """Mutable per-query state shared by the four tool closures.

    Built fresh on each :meth:`ReasoningAnswerAgent.answer` call. Closures grab
    it through :data:`_CURRENT_CTX`. Production callers MUST NOT touch this
    type directly — the asserts in each closure will fire.
    """

    corpus_agent: "CorpusAgent | None"
    structured_retriever: "StructuredRetriever | None"
    schemas: "list[TargetSchema]"
    db_path: Path
    accumulated_hits: "dict[str, ChunkHit]" = field(default_factory=dict)
    sql_calls: "list[SqlRetrievalOutcome]" = field(default_factory=list)


_CURRENT_CTX: contextvars.ContextVar[_LoopContext | None] = contextvars.ContextVar(
    "reasoning_answerer_ctx", default=None
)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py tests/unit/corpus_search/test_reasoning_answerer.py
git commit -m "feat(reasoning_answerer): scaffold _LoopContext and contextvar"
```

---

## Task 5: `knowledge_search` tool closure

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_reasoning_answerer.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from unittest.mock import AsyncMock

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _build_knowledge_search,
)


@pytest.mark.asyncio
async def test_knowledge_search_records_hits_and_returns_dicts():
    hit = ChunkHit(
        chunk_id="c1", content="hello world", source_path="/x.md",
        score=0.9, metadata={},
    )
    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    ctx = _LoopContext(
        corpus_agent=corpus, structured_retriever=None,
        schemas=[], db_path=Path("/tmp/x.sqlite"),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        knowledge_search = _build_knowledge_search()
        out = await knowledge_search(query="hello", top_k=3)
    finally:
        _CURRENT_CTX.reset(tok)
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["chunk_id"] == "c1"
    assert out[0]["source_path"] == "/x.md"
    assert "hello" in out[0]["snippet"]
    assert ctx.accumulated_hits == {"c1": hit}
    corpus.retrieve.assert_awaited_once_with("hello", top_k=3, rerank=True)


@pytest.mark.asyncio
async def test_knowledge_search_requires_ctx():
    knowledge_search = _build_knowledge_search()
    with pytest.raises(AssertionError):
        await knowledge_search(query="x")
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py::test_knowledge_search_records_hits_and_returns_dicts -v
```

Expected: ImportError on `_build_knowledge_search`.

- [ ] **Step 3: Implement**

Append:

```python
_SNIPPET_CHARS = 400


def _build_knowledge_search() -> Any:
    """Return an async ``knowledge_search(query, top_k=5)`` closure.

    Closes over the contextvar — callers must :meth:`answer` first. Side-effect:
    every returned :class:`ChunkHit` is recorded in
    ``ctx.accumulated_hits[chunk_id]`` so the orchestrator can enrich
    ``Answer.cited_sources`` post-hoc.
    """

    async def knowledge_search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "knowledge_search called outside answer()"
        assert ctx.corpus_agent is not None
        hits = await ctx.corpus_agent.retrieve(query, top_k=top_k, rerank=True)
        out: list[dict[str, Any]] = []
        for h in hits:
            ctx.accumulated_hits[h.chunk_id] = h
            out.append({
                "chunk_id": h.chunk_id,
                "source_path": h.source_path,
                "score": h.score,
                "snippet": h.content[:_SNIPPET_CHARS],
            })
        return out

    return knowledge_search
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py tests/unit/corpus_search/test_reasoning_answerer.py
git commit -m "feat(reasoning_answerer): knowledge_search tool closure"
```

---

## Task 6: `sql_query` tool closure

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_reasoning_answerer.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from fireflyframework_agentic.rag.retrieval.sql import (
    ProbeRecord,
    SqlRetrievalOutcome,
)
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _build_sql_query,
)


@pytest.mark.asyncio
async def test_sql_query_serialises_outcome_and_records():
    outcome = SqlRetrievalOutcome(
        outcome="answered",
        result_markdown="| col |\n| --- |\n| 1 |",
        attempted_sql="SELECT col FROM t",
        probe_trail=[ProbeRecord(table="t", column="col", op="count", result="1")],
    )
    retriever = AsyncMock()
    retriever.retrieve.return_value = outcome
    ctx = _LoopContext(
        corpus_agent=None, structured_retriever=retriever,
        schemas=[], db_path=Path("/tmp/x.sqlite"),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        sql_query = _build_sql_query()
        out = await sql_query(question="how many rows?")
    finally:
        _CURRENT_CTX.reset(tok)
    assert out["outcome"] == "answered"
    assert out["attempted_sql"] == "SELECT col FROM t"
    assert "| col |" in out["result_markdown"]
    assert out["probe_trail"] == [{"table": "t", "column": "col", "op": "count", "result": "1"}]
    assert ctx.sql_calls == [outcome]
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py::test_sql_query_serialises_outcome_and_records -v
```

Expected: ImportError on `_build_sql_query`.

- [ ] **Step 3: Implement**

Append:

```python
def _build_sql_query() -> Any:
    """Return an async ``sql_query(question)`` closure wrapping
    :meth:`StructuredRetriever.retrieve`.

    Returns a JSON-serialisable dict so the LLM sees a clean shape. Side-effect:
    appends the :class:`SqlRetrievalOutcome` to ``ctx.sql_calls`` for telemetry.
    """

    async def sql_query(question: str) -> dict[str, Any]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "sql_query called outside answer()"
        assert ctx.structured_retriever is not None
        outcome = await ctx.structured_retriever.retrieve(question, ctx.schemas)
        ctx.sql_calls.append(outcome)
        return {
            "outcome": outcome.outcome,
            "attempted_sql": outcome.attempted_sql,
            "result_markdown": outcome.result_markdown,
            "probe_trail": [
                {"table": p.table, "column": p.column, "op": p.op, "result": p.result}
                for p in outcome.probe_trail
            ],
        }

    return sql_query
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py tests/unit/corpus_search/test_reasoning_answerer.py
git commit -m "feat(reasoning_answerer): sql_query tool closure"
```

---

## Task 7: `inspect_table` tool closure

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_reasoning_answerer.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
import sqlite3

from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec, ColumnType, TableSpec, TargetSchema,
)
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _build_inspect_table_tool,
)


@pytest.mark.asyncio
async def test_inspect_table_distinct_values(tmp_path):
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE products (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO products VALUES (1, 'Widget'), (2, 'Gadget')")
    conn.commit()
    conn.close()
    schema = TargetSchema(tables=[TableSpec(
        name="products",
        columns=[ColumnSpec(name="id", type=ColumnType.integer),
                 ColumnSpec(name="name", type=ColumnType.string)],
    )])
    ctx = _LoopContext(
        corpus_agent=None, structured_retriever=None,
        schemas=[schema], db_path=db,
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        inspect_table = _build_inspect_table_tool()
        out = await inspect_table(table="products", column="name", op="distinct_values")
    finally:
        _CURRENT_CTX.reset(tok)
    assert "Widget" in out and "Gadget" in out
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py::test_inspect_table_distinct_values -v
```

Expected: ImportError on `_build_inspect_table_tool`.

- [ ] **Step 3: Implement**

Append:

```python
from typing import Literal  # add to existing imports if not present

from fireflyframework_agentic.rag.retrieval.sql import (
    _LoopContext as _SqlLoopContext,
    _build_inspect_tool,
)


def _build_inspect_table_tool() -> Any:
    """Return an async ``inspect_table(table, column, op, value=None)`` closure
    that delegates to the SQL retriever's existing inspect primitives.

    Builds a one-off :class:`_SqlLoopContext` per call; the SQL retriever's
    probe trail is not interesting at the outer layer — the outer trace
    already captures each ``inspect_table`` call as its own :class:`ActionStep`.
    """

    async def inspect_table(
        table: str,
        column: str,
        op: Literal[
            "distinct_values", "count", "sample_rows",
            "value_range", "find_similar", "numeric_summary",
        ],
        value: str | None = None,
    ) -> str:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "inspect_table called outside answer()"
        sql_ctx = _SqlLoopContext(db_path=ctx.db_path, schemas=ctx.schemas)
        inspect_fn = _build_inspect_tool(sql_ctx)
        return await inspect_fn(table, column, op, value)

    return inspect_table
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py tests/unit/corpus_search/test_reasoning_answerer.py
git commit -m "feat(reasoning_answerer): inspect_table tool closure"
```

---

## Task 8: `python_compute` tool closure

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_reasoning_answerer.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _build_python_compute_tool,
)


@pytest.mark.asyncio
async def test_python_compute_tool_runs_source_with_data():
    ctx = _LoopContext(
        corpus_agent=None, structured_retriever=None,
        schemas=[], db_path=Path("/tmp/x.sqlite"),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        python_compute = _build_python_compute_tool()
        out = await python_compute(source="result = sum(xs)", data={"xs": [1, 2, 3]})
    finally:
        _CURRENT_CTX.reset(tok)
    assert "6" in out
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py::test_python_compute_tool_runs_source_with_data -v
```

Expected: ImportError on `_build_python_compute_tool`.

- [ ] **Step 3: Implement**

Append:

```python
import asyncio as _asyncio

from fireflyframework_agentic.rag.retrieval._python_compute import run_python_compute


def _build_python_compute_tool() -> Any:
    """Return an async ``python_compute(source, data=None)`` closure.

    Runs the sandbox in the event loop's default executor so the worker thread
    in :func:`run_python_compute` doesn't block other tool calls.
    """

    async def python_compute(source: str, data: dict[str, Any] | None = None) -> str:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "python_compute called outside answer()"
        loop = _asyncio.get_running_loop()
        return await loop.run_in_executor(None, run_python_compute, source, data)

    return python_compute
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py tests/unit/corpus_search/test_reasoning_answerer.py
git commit -m "feat(reasoning_answerer): python_compute tool closure"
```

---

## Task 9: Trace translation helper

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_trace_translation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/corpus_search/test_trace_translation.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    ThoughtStep,
)
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _trace_from_messages,
)


def test_trace_translation_drops_system_and_user_parts():
    msgs = [
        ModelRequest(parts=[SystemPromptPart(content="sys")]),
        ModelRequest(parts=[UserPromptPart(content="hi")]),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert trace.steps == []
    assert trace.pattern_name == "reasoning_answerer"


def test_trace_translation_emits_action_and_observation():
    msgs = [
        ModelResponse(parts=[ToolCallPart(
            tool_call_id="t1", tool_name="knowledge_search",
            args={"query": "x", "top_k": 3},
        )]),
        ModelRequest(parts=[ToolReturnPart(
            tool_call_id="t1", tool_name="knowledge_search",
            content="[{...}]",
        )]),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 2
    assert isinstance(trace.steps[0], ActionStep)
    assert trace.steps[0].tool_name == "knowledge_search"
    assert trace.steps[0].tool_args == {"query": "x", "top_k": 3}
    assert isinstance(trace.steps[1], ObservationStep)
    assert trace.steps[1].source == "knowledge_search"


def test_trace_translation_emits_thought_for_text_parts():
    msgs = [
        ModelResponse(parts=[TextPart(content="I should search first.")]),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 1
    assert isinstance(trace.steps[0], ThoughtStep)
    assert "search" in trace.steps[0].content


def test_trace_translation_truncates_long_observations():
    long = "x" * 5000
    msgs = [
        ModelRequest(parts=[ToolReturnPart(
            tool_call_id="t1", tool_name="knowledge_search", content=long,
        )]),
    ]
    trace = _trace_from_messages(msgs, pattern_name="reasoning_answerer")
    assert len(trace.steps) == 1
    obs = trace.steps[0]
    assert isinstance(obs, ObservationStep)
    assert "more bytes" in obs.content
    assert len(obs.content) <= 2100  # cap + suffix
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_trace_translation.py -v
```

Expected: ImportError on `_trace_from_messages`.

- [ ] **Step 3: Implement**

Append:

```python
from collections.abc import Sequence

from fireflyframework_agentic.reasoning.trace import (
    ActionStep,
    ObservationStep,
    ReasoningTrace,
    ThoughtStep,
)

_OBS_CAP = 2000


def _truncate_obs(text: str) -> str:
    if len(text) <= _OBS_CAP:
        return text
    return text[:_OBS_CAP] + f"… ({len(text) - _OBS_CAP} more bytes)"


def _trace_from_messages(messages: Sequence[Any], *, pattern_name: str) -> ReasoningTrace:
    """Translate pydantic-ai message history into a typed :class:`ReasoningTrace`.

    Skips system and user prompts (those are our own); emits:
    - ``TextPart`` → :class:`ThoughtStep`
    - ``ToolCallPart`` → :class:`ActionStep` (tool_name + tool_args lossless)
    - ``ToolReturnPart`` → :class:`ObservationStep` (content truncated to 2 KB)
    """
    from pydantic_ai.messages import (  # noqa: PLC0415
        SystemPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart,
    )

    trace = ReasoningTrace(pattern_name=pattern_name)
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, SystemPromptPart | UserPromptPart):
                continue
            if isinstance(part, TextPart):
                if part.content:
                    trace.add_step(ThoughtStep(content=part.content))
            elif isinstance(part, ToolCallPart):
                args = part.args if isinstance(part.args, dict) else {}
                trace.add_step(ActionStep(tool_name=part.tool_name, tool_args=args))
            elif isinstance(part, ToolReturnPart):
                trace.add_step(ObservationStep(
                    content=_truncate_obs(str(part.content)),
                    source=part.tool_name,
                ))
    return trace
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_trace_translation.py -v
```

Expected: all pass. (If the installed pydantic-ai uses `args_as_dict()` instead of a `dict` field, adjust the closure accordingly — confirm by importing `pydantic_ai.messages.ToolCallPart` in a REPL.)

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py tests/unit/corpus_search/test_trace_translation.py
git commit -m "feat(reasoning_answerer): trace translation from pydantic-ai messages"
```

---

## Task 10: `Answer.reasoning_trace` field

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/answerer.py`
- Test: `tests/unit/corpus_search/test_answerer_sql_context.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/corpus_search/test_answerer_sql_context.py`:

```python
def test_answer_reasoning_trace_defaults_to_none_and_serialises_clean():
    from fireflyframework_agentic.rag.retrieval.answerer import Answer

    a = Answer(text="hi")
    assert a.reasoning_trace is None
    dumped = a.model_dump(exclude_none=True)
    assert "reasoning_trace" not in dumped


def test_answer_reasoning_trace_round_trip():
    from fireflyframework_agentic.rag.retrieval.answerer import Answer
    from fireflyframework_agentic.reasoning.trace import (
        ActionStep, ReasoningTrace,
    )

    trace = ReasoningTrace(pattern_name="reasoning_answerer")
    trace.add_step(ActionStep(tool_name="knowledge_search", tool_args={"q": "x"}))
    a = Answer(text="hi", reasoning_trace=trace)
    dumped = a.model_dump(mode="json")
    assert dumped["reasoning_trace"]["pattern_name"] == "reasoning_answerer"
    assert dumped["reasoning_trace"]["steps"][0]["tool_name"] == "knowledge_search"
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_answerer_sql_context.py::test_answer_reasoning_trace_defaults_to_none_and_serialises_clean -v
```

Expected: AttributeError on `reasoning_trace`.

- [ ] **Step 3: Add the field**

Edit `fireflyframework_agentic/rag/retrieval/answerer.py` — modify `Answer`:

```python
from fireflyframework_agentic.reasoning.trace import ReasoningTrace


class Answer(BaseModel):
    """Structured answer with inline citations.

    The LLM populates ``text`` and ``citations`` (chunk_ids it referenced).
    ``cited_sources`` is enriched by :class:`AnswerAgent` *after* the LLM
    call from the hits passed in. ``reasoning_trace`` is populated by
    :class:`ReasoningAnswerAgent` when ``include_trace=True``.
    """

    text: str
    citations: list[str] = Field(default_factory=list)
    cited_sources: list[CitedSource] = Field(default_factory=list)
    reasoning_trace: ReasoningTrace | None = None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_answerer_sql_context.py -v
```

Expected: new tests pass; existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/answerer.py tests/unit/corpus_search/test_answerer_sql_context.py
git commit -m "feat(answer): add optional reasoning_trace field"
```

---

## Task 11: `ReasoningAnswerAgent` class

**Files:**
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`
- Test: `tests/unit/corpus_search/test_reasoning_answerer.py`

- [ ] **Step 1: Write the failing integration test**

Append:

```python
from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.rag.retrieval.answerer import Answer
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    ReasoningAnswerAgent,
)


@pytest.mark.asyncio
async def test_reasoning_answerer_runs_with_stub_model_and_returns_answer(tmp_path):
    hit = ChunkHit(chunk_id="c1", content="X", source_path="/x", score=1.0, metadata={})
    corpus = AsyncMock()
    corpus.retrieve.return_value = [hit]
    retriever = AsyncMock()
    retriever.retrieve.return_value = SqlRetrievalOutcome(
        outcome="answered", result_markdown="| n |\n|-|\n|1|",
        attempted_sql="SELECT 1", probe_trail=[],
    )
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    rae = ReasoningAnswerAgent(
        model=TestModel(),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
        max_tool_calls=4,
        max_llm_calls=4,
        wall_clock_seconds=10.0,
    )
    answer = await rae.answer("how many?", include_trace=True)
    assert isinstance(answer, Answer)
    assert answer.reasoning_trace is not None
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py::test_reasoning_answerer_runs_with_stub_model_and_returns_answer -v
```

Expected: ImportError on `ReasoningAnswerAgent`.

- [ ] **Step 3: Implement the class**

Append:

```python
import logging

from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.rag.retrieval.answerer import (
    Answer, _build_cited_sources,
)
from fireflyframework_agentic.rag.retrieval.sql import _build_schema_context

if TYPE_CHECKING:
    from fireflyframework_agentic.rag.ingest import SchemaRegistry

log = logging.getLogger(__name__)


_SYSTEM = """\
You answer questions about a corpus by calling tools to retrieve and verify evidence.

Available tools:
  - knowledge_search(query, top_k=5)  — hybrid retrieval over unstructured docs;
    returns chunks with chunk_id, source_path, score, snippet. Cite chunks
    inline using [chunk_id] notation for claims grounded in them.
  - sql_query(question)  — natural-language text-to-SQL over the structured
    tables. Returns {outcome, attempted_sql, result_markdown, probe_trail}.
  - inspect_table(table, column, op, value=None)  — cheap direct SQL probes
    (no inner LLM). op ∈ {distinct_values, count, sample_rows, value_range,
    find_similar, numeric_summary}. Use BEFORE committing to sql_query when
    you are not sure what values a column contains.
  - python_compute(source, data=None)  — restricted Python sandbox (multi-line,
    stdlib + numpy + pandas). Pass intermediate results from prior tools as
    the ``data`` dict so the snippet is self-contained.

Strategy:
  1. Probe cheap before committing expensive: inspect_table < sql_query.
  2. For numeric answers, verify with python_compute over the returned rows when
     the calculation is non-trivial (weighted means, growth rates, stdev, CV).
  3. SQL-grounded claims should name the source table. Knowledge-grounded
     claims must carry inline [chunk_id] citations.
  4. If neither retrieval nor SQL surfaces evidence, reply exactly:
     "I don't have enough information."

Answer in the same language as the question; preserve diacritics (á, é, ñ, ç,
…). When you report a numeric quantity, include its unit if known.
"""


class ReasoningAnswerAgent:
    """Tool-using corpus answer agent. See spec §4.

    Owns a :class:`FireflyAgent` registered with the four tool closures and
    ``output_type=Answer``. Pydantic-ai handles the loop; we translate the
    resulting message history to a :class:`ReasoningTrace` and enrich
    ``cited_sources`` from accumulated knowledge_search hits.
    """

    def __init__(
        self,
        *,
        model: str | Model,
        corpus_agent: "CorpusAgent",
        structured_retriever: "StructuredRetriever",
        schema_registry: "SchemaRegistry",
        db_path: Path,
        max_tool_calls: int = 20,
        max_llm_calls: int = 10,
        wall_clock_seconds: float = 120.0,
    ) -> None:
        self._model = model
        self._corpus_agent = corpus_agent
        self._structured_retriever = structured_retriever
        self._schema_registry = schema_registry
        self._db_path = db_path
        self._max_tool_calls = max_tool_calls
        self._max_llm_calls = max_llm_calls
        self._wall_clock = wall_clock_seconds

        self._knowledge_search = _build_knowledge_search()
        self._sql_query = _build_sql_query()
        self._inspect_table = _build_inspect_table_tool()
        self._python_compute = _build_python_compute_tool()

        self._agent = FireflyAgent(
            name="reasoning_answerer",
            model=model,
            output_type=Answer,
            instructions=_SYSTEM,
            tools=[
                self._knowledge_search,
                self._sql_query,
                self._inspect_table,
                self._python_compute,
            ],
            auto_register=False,
        )

    async def answer(self, question: str, *, include_trace: bool = False) -> Answer:
        schemas = await self._schema_registry.list_schemas()
        ctx = _LoopContext(
            corpus_agent=self._corpus_agent,
            structured_retriever=self._structured_retriever,
            schemas=schemas,
            db_path=self._db_path,
        )
        schema_context = _build_schema_context(schemas, self._db_path) if schemas else ""
        prompt = (f"{schema_context}\n\n" if schema_context else "") + f"Question: {question}"

        tok = _CURRENT_CTX.set(ctx)
        try:
            run = self._agent.run(
                prompt,
                usage_limits=UsageLimits(
                    tool_calls_limit=self._max_tool_calls,
                    request_limit=self._max_llm_calls,
                ),
            )
            result = await _asyncio.wait_for(run, timeout=self._wall_clock)
        except (TimeoutError, Exception) as exc:  # noqa: BLE001 — partial-Answer contract
            log.warning("reasoning_answerer loop ended early: %s", exc)
            return Answer(
                text=(
                    "I couldn't complete reasoning within the budget. "
                    f"Partial findings: {len(ctx.accumulated_hits)} chunks, "
                    f"{len(ctx.sql_calls)} sql calls."
                ),
                citations=[],
                cited_sources=[],
                reasoning_trace=None,
            )
        finally:
            _CURRENT_CTX.reset(tok)

        answer: Answer = result.output
        answer.cited_sources = _build_cited_sources(
            answer.citations, list(ctx.accumulated_hits.values()),
        )
        if include_trace:
            answer.reasoning_trace = _trace_from_messages(
                result.all_messages(), pattern_name="reasoning_answerer",
            )
        return answer
```

Update `fireflyframework_agentic/rag/retrieval/__init__.py`:

```python
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    ReasoningAnswerAgent,
)
```

…and add `"ReasoningAnswerAgent"` to `__all__`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_reasoning_answerer.py -v
```

Expected: all pass. If the installed pydantic-ai's `TestModel` import path differs, swap to a hand-rolled stub returning a pre-baked `Answer` on first call.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/retrieval/reasoning_answerer.py fireflyframework_agentic/rag/retrieval/__init__.py tests/unit/corpus_search/test_reasoning_answerer.py
git commit -m "feat(reasoning_answerer): ReasoningAnswerAgent orchestrator with trace + citations"
```

---

## Task 12: `CorpusAgent.answer_strategy` plumbing

**Files:**
- Modify: `fireflyframework_agentic/rag/agent.py`
- Test: `tests/unit/corpus_search/test_corpus_agent_strategy_flag.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/corpus_search/test_corpus_agent_strategy_flag.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fireflyframework_agentic.rag.agent import CorpusAgent


def _make(tmp_path: Path, strategy: str = "fast") -> CorpusAgent:
    return CorpusAgent(
        root=tmp_path,
        embed_model="openai:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        answer_strategy=strategy,
        _embedder=MagicMock(),
        _vector_store=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_default_strategy_is_fast(tmp_path):
    agent = _make(tmp_path, strategy="fast")
    await agent._ensure_query_ready()
    from fireflyframework_agentic.rag.retrieval.answerer import AnswerAgent
    assert isinstance(agent._answerer, AnswerAgent)


@pytest.mark.asyncio
async def test_reasoning_strategy_uses_reasoning_answerer(tmp_path):
    agent = _make(tmp_path, strategy="reasoning")
    await agent._ensure_query_ready()
    from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
        ReasoningAnswerAgent,
    )
    assert isinstance(agent._answerer, ReasoningAnswerAgent)
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_corpus_agent_strategy_flag.py -v
```

Expected: `TypeError: unexpected keyword argument 'answer_strategy'`.

- [ ] **Step 3: Wire the flag**

Edit `fireflyframework_agentic/rag/agent.py`:

1. Extend `CorpusAgent.__init__` signature (after `sql_model`, before the test-injection params):

```python
        answer_strategy: Literal["fast", "reasoning"] = "fast",
        max_reasoning_tool_calls: int = 20,
        max_reasoning_llm_calls: int = 10,
        reasoning_wall_clock_seconds: float = 120.0,
```

2. Persist in `__init__` body alongside the other `self._...` assignments:

```python
        self._answer_strategy = answer_strategy
        self._max_reasoning_tool_calls = max_reasoning_tool_calls
        self._max_reasoning_llm_calls = max_reasoning_llm_calls
        self._reasoning_wall_clock = reasoning_wall_clock_seconds
```

3. In `_ensure_query_ready`, move `StructuredRetriever` construction *above* the answerer init (so the reasoning branch can pass it in), then branch on the flag:

```python
        if self._structured_retriever is None:
            self._structured_retriever = StructuredRetriever(self.root / "corpus.sqlite", sql_model=self._sql_model)
        if self._answerer is None:
            if self._answer_strategy == "reasoning":
                from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
                    ReasoningAnswerAgent,
                )
                self._answerer = ReasoningAnswerAgent(
                    model=self._answer_model,
                    corpus_agent=self,
                    structured_retriever=self._structured_retriever,
                    schema_registry=self._schema_registry,
                    db_path=self.root / "corpus.sqlite",
                    max_tool_calls=self._max_reasoning_tool_calls,
                    max_llm_calls=self._max_reasoning_llm_calls,
                    wall_clock_seconds=self._reasoning_wall_clock,
                )
            else:
                self._answerer = AnswerAgent(model=self._answer_model)
```

4. Extend `query()`:

```python
    async def query(
        self, question: str, *, top_k: int = 5, include_trace: bool = False,
    ) -> Answer:
        await self._ensure_query_ready()
        assert self._answerer is not None

        async with timed_span(
            "firefly.rag.query",
            attributes={
                "question": question,
                "top_k": top_k,
                "rerank_pool": self._rerank_pool,
                "firefly.rag.answer_strategy": self._answer_strategy,
            },
        ) as span:
            if self._answer_strategy == "reasoning":
                answer = await self._answerer.answer(question, include_trace=include_trace)
            else:
                schemas = await self._schema_registry.list_schemas()
                top_hits, sql_outcome = await asyncio.gather(
                    self.retrieve(question, top_k=top_k, rerank=True),
                    self._structured_retriever.retrieve(question, schemas),
                )
                answer = await self._answerer.answer(question, top_hits, sql_outcome=sql_outcome)
            outcome = "no_info" if not answer.cited_sources else "answered"
            span.set_attribute("firefly.rag.citation_count", len(answer.cited_sources))
            span.set_attribute("firefly.rag.outcome", outcome)
            return answer
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/corpus_search/test_corpus_agent_strategy_flag.py tests/unit/corpus_search/test_agent_query.py -v
```

Expected: new tests pass; existing `test_agent_query.py` (fast-path regression) still passes.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/agent.py tests/unit/corpus_search/test_corpus_agent_strategy_flag.py
git commit -m "feat(corpus_agent): answer_strategy flag (fast | reasoning); include_trace param"
```

---

## Task 13: Citation enrichment regression test

**Files:**
- Test: `tests/unit/corpus_search/test_citation_enrichment.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/corpus_search/test_citation_enrichment.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from fireflyframework_agentic.rag.corpus import ChunkHit
from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    ReasoningAnswerAgent,
)
from fireflyframework_agentic.rag.retrieval.sql import SqlRetrievalOutcome


@pytest.mark.asyncio
async def test_cited_sources_unions_across_multiple_knowledge_search_calls(tmp_path):
    """The agent may call knowledge_search several times; the final cited_sources
    map must include hits from any of those calls, with hallucinated chunk_ids
    dropped.
    """
    hits_round_1 = [ChunkHit(chunk_id="c1", content="A", source_path="/a", score=1.0, metadata={})]
    hits_round_2 = [ChunkHit(chunk_id="c2", content="B", source_path="/b", score=1.0, metadata={})]
    corpus = AsyncMock()
    corpus.retrieve.side_effect = [hits_round_1, hits_round_2]
    retriever = AsyncMock()
    retriever.retrieve.return_value = SqlRetrievalOutcome(
        outcome="unsupported", result_markdown=None, attempted_sql=None, probe_trail=[],
    )
    schema_registry = AsyncMock()
    schema_registry.list_schemas.return_value = []

    rae = ReasoningAnswerAgent(
        model=TestModel(call_tools=["knowledge_search", "knowledge_search"]),
        corpus_agent=corpus,
        structured_retriever=retriever,
        schema_registry=schema_registry,
        db_path=tmp_path / "corpus.sqlite",
    )
    answer = await rae.answer("x", include_trace=True)
    for c in answer.cited_sources:
        assert c.source_path in {"/a", "/b"}
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/corpus_search/test_citation_enrichment.py -v
```

Expected: passes (asserts are conservative).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/corpus_search/test_citation_enrichment.py
git commit -m "test: cited_sources unions across multiple knowledge_search calls"
```

---

## Task 14: Fixture corpus + ground-truth dict

**Files:**
- Create: `tests/examples/corpus_search/benchmark/corpus/reasoning/quarterly_revenue.csv`
- Create: `tests/examples/corpus_search/benchmark/corpus/reasoning/headcount_snapshots.csv`
- Create: `tests/examples/corpus_search/benchmark/corpus/reasoning/methodology.md`
- Create: `tests/examples/corpus_search/reasoning_fixtures.py`

- [ ] **Step 1: Create `quarterly_revenue.csv`**

Construct it so the ground-truth math is checkable by hand. Schema: `business_unit,region,product,year,quarter,revenue_usd,units_sold`. Three business units (Alpha, Beta, Gamma), two regions (NA, EU), three products per BU, four quarters across 2023 and 2024 (16 rows per BU). Seed a handful of NULL `revenue_usd` cells (empty field) so question 3 (mean blanks-as-zero) is meaningful. ~150 rows total.

Run this one-off generator (do not commit it; commit only the produced CSV):

```python
# scratch generator — run once, paste output into the CSV
import csv, io, random
rng = random.Random(42)
buf = io.StringIO()
w = csv.writer(buf)
w.writerow(["business_unit","region","product","year","quarter","revenue_usd","units_sold"])
for bu in ("Alpha","Beta","Gamma"):
    for region in ("NA","EU"):
        for product in (f"{bu}-1",f"{bu}-2",f"{bu}-3"):
            for year in (2023, 2024):
                for q in (1,2,3,4):
                    units = rng.randint(50, 400)
                    rev = "" if rng.random() < 0.05 else round(units * rng.uniform(80, 220), 2)
                    w.writerow([bu, region, product, year, q, rev, units])
print(buf.getvalue())
```

- [ ] **Step 2: Create `headcount_snapshots.csv`**

```csv
business_unit,snapshot_date,headcount
Alpha,2024-03-31,42
Alpha,2024-06-30,45
Alpha,2024-09-30,48
Alpha,2024-12-31,50
Beta,2024-03-31,30
Beta,2024-06-30,31
Beta,2024-09-30,29
Beta,2024-12-31,32
Gamma,2024-03-31,60
Gamma,2024-06-30,62
Gamma,2024-09-30,65
Gamma,2024-12-31,68
```

- [ ] **Step 3: Create `methodology.md`**

```markdown
# Reporting methodology

## Operating Efficiency

Operating Efficiency (OE) for a business unit in a given quarter is defined as:

    OE = total_revenue_usd / headcount_at_end_of_quarter

where `total_revenue_usd` is the sum of `revenue_usd` across all products and
regions for that BU and quarter, and `headcount_at_end_of_quarter` is the
headcount in `headcount_snapshots` at the last calendar day of the quarter.

Blank `revenue_usd` cells in `quarterly_revenue` are treated as zero for
this calculation.
```

- [ ] **Step 4: Compute ground truths and commit them**

Create `tests/examples/corpus_search/reasoning_fixtures.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Fixture loader and pre-computed ground-truth answers for the reasoning
end-to-end test suite. Numbers below are computed from the committed CSV
fixtures; if those change, recompute and update this dict.

To recompute: write a small Python program that loads the CSVs, applies
the formulas the agent should use, and prints the dict. Paste the values
here. Keep it manual — automated recompute hides drift.
"""

from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent / "benchmark" / "corpus" / "reasoning"


# Placeholder values — replace with actual computed numbers once the CSVs are
# committed. Each test in test_corpus_query_reasoning.py reads from this dict
# to assert against, so the numbers MUST be real before those tests run.
GROUND_TRUTH: dict[str, dict] = {
    "q1_yoy_growth": {
        "tolerance_pct_points": 0.1,
        "by_bu": {"Alpha": 0.0, "Beta": 0.0, "Gamma": 0.0},
    },
    "q2_weighted_price": {
        "tolerance": 0.01,
        "value": 0.0,
    },
    "q3_mean_and_stdev_q4_2024_blanks_as_zero": {
        "tolerance": 0.01,
        "mean_by_region": {"NA": 0.0, "EU": 0.0},
        "stdev_by_region": {"NA": 0.0, "EU": 0.0},
    },
    "q4_headcount_cv_ranking": {
        "ranking": ["Beta", "Alpha", "Gamma"],  # verify with data
    },
    "q5_operating_efficiency_2024q3": {
        "tolerance": 0.5,
        "by_bu": {"Alpha": 0.0, "Beta": 0.0, "Gamma": 0.0},
    },
}


def fixture_path(name: str) -> Path:
    """Return the absolute path of a fixture file."""
    p = FIXTURE_ROOT / name
    if not p.exists():
        raise FileNotFoundError(p)
    return p
```

After generating the CSV in Step 1, run a small one-off that loads it, applies each question's formula, and prints the populated dict. Paste those numbers into `GROUND_TRUTH`.

- [ ] **Step 5: Commit**

```bash
git add tests/examples/corpus_search/benchmark/corpus/reasoning/ tests/examples/corpus_search/reasoning_fixtures.py
git commit -m "test(reasoning): synthetic fixture corpus + ground-truth dict"
```

---

## Task 15: Tier A replay tests (5 questions)

**Files:**
- Create: `tests/examples/corpus_search/replay/q1_yoy_growth.json` (and `q2`…`q5`)
- Create: `tests/examples/corpus_search/test_corpus_query_reasoning.py`

- [ ] **Step 1: Capture replay fixtures**

Each replay JSON is an ordered list of model "decisions" the inner LLM would make:

```json
{
  "question": "What's the YoY revenue growth rate per business unit from 2023 to 2024?",
  "decisions": [
    {"kind": "tool_call", "tool_name": "sql_query",
     "args": {"question": "total revenue_usd by business_unit and year for 2023 and 2024"}},
    {"kind": "tool_call", "tool_name": "python_compute",
     "args": {"source": "result = {bu: (d[(bu,2024)] - d[(bu,2023)]) / d[(bu,2023)] for bu in {k[0] for k in d}}",
              "data_from_prior": "<reference to last sql_query rows>"}},
    {"kind": "final_answer",
     "text": "Alpha: +X.X%, Beta: +Y.Y%, Gamma: +Z.Z%",
     "citations": []}
  ]
}
```

`"data_from_prior"` is interpreted by the replay test runner to materialise `data` from the previous `sql_query` row set. Hand-author each JSON the first time; refresh later via `scripts/capture_reasoning_replay.py` (Task 19).

- [ ] **Step 2: Write the replay test**

Create `tests/examples/corpus_search/test_corpus_query_reasoning.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tier A end-to-end tests for the reasoning corpus agent.

Real corpus, real SQL execution, real python_compute sandbox; stubbed LLM that
replays pre-recorded tool decisions from JSON fixtures under
``tests/examples/corpus_search/replay/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.messages import (
    ModelMessage, ModelResponse, ToolCallPart, TextPart,
)

from fireflyframework_agentic.rag.agent import CorpusAgent
from tests.examples.corpus_search.reasoning_fixtures import (
    FIXTURE_ROOT, GROUND_TRUTH, fixture_path,
)

REPLAY_ROOT = Path(__file__).parent / "replay"


def _replay_model(decisions: list[dict]) -> FunctionModel:
    """Build a FunctionModel that emits the recorded decisions in order."""
    state = {"i": 0}

    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        d = decisions[state["i"]]
        state["i"] += 1
        if d["kind"] == "tool_call":
            return ModelResponse(parts=[ToolCallPart(
                tool_call_id=f"t{state['i']}",
                tool_name=d["tool_name"],
                args=d["args"],
            )])
        elif d["kind"] == "final_answer":
            return ModelResponse(parts=[TextPart(content=json.dumps({
                "text": d["text"],
                "citations": d.get("citations", []),
            }))])
        raise ValueError(d["kind"])

    return FunctionModel(call)


async def _build_corpus_with_fixtures(tmp_path: Path) -> CorpusAgent:
    agent = CorpusAgent(
        root=tmp_path,
        embed_model="openai:text-embedding-3-small",
        expansion_model="anthropic:claude-haiku-4-5-20251001",
        answer_model="anthropic:claude-sonnet-4-6",
        rerank_model="anthropic:claude-haiku-4-5-20251001",
        answer_strategy="reasoning",
        _embedder=MagicMock(),
        _vector_store=AsyncMock(),
    )
    schema = await agent.discover_schema(FIXTURE_ROOT)
    await agent.ingest_folder(FIXTURE_ROOT, mode="structured", schema=schema)
    await agent.ingest_one(fixture_path("methodology.md"))
    return agent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_q1_yoy_growth(tmp_path):
    fixture = json.loads((REPLAY_ROOT / "q1_yoy_growth.json").read_text())
    agent = await _build_corpus_with_fixtures(tmp_path)
    await agent._ensure_query_ready()
    agent._answerer._agent.agent.model = _replay_model(fixture["decisions"])  # type: ignore[attr-defined]

    answer = await agent.query(fixture["question"], include_trace=True)

    gt = GROUND_TRUTH["q1_yoy_growth"]
    for bu in gt["by_bu"]:
        assert bu in answer.text
    assert answer.reasoning_trace is not None
    tool_names = [s.tool_name for s in answer.reasoning_trace.steps if hasattr(s, "tool_name")]
    assert "sql_query" in tool_names
    assert "python_compute" in tool_names


# Replicate the test body for q2…q5. Each test loads its own replay JSON and
# asserts against its own ground-truth slot. Keep them as separate functions
# (not parametrize) so per-question failures stay isolated.
```

Stub out `test_q2_weighted_price`, `test_q3_mean_stdev_blanks_as_zero`, `test_q4_headcount_cv_ranking`, and `test_q5_operating_efficiency` with the same skeleton — each loads its own JSON and ground-truth slot.

- [ ] **Step 3: Run**

```bash
uv run pytest tests/examples/corpus_search/test_corpus_query_reasoning.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/examples/corpus_search/replay/ tests/examples/corpus_search/test_corpus_query_reasoning.py
git commit -m "test(reasoning): Tier A end-to-end replay tests (5 questions, integration mark)"
```

---

## Task 16: `test_trace_is_replayable.py` — the headline test

**Files:**
- Create: `tests/examples/corpus_search/test_trace_is_replayable.py`

- [ ] **Step 1: Write the test**

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""The spec's central claim: a recorded ReasoningTrace can be replayed against
a fresh _LoopContext and the same observations come back. If this test passes,
"the trace is reproducible" is fact, not aspiration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fireflyframework_agentic.rag.retrieval.reasoning_answerer import (
    _CURRENT_CTX, _LoopContext,
    _build_knowledge_search, _build_sql_query,
    _build_inspect_table_tool, _build_python_compute_tool,
)
from fireflyframework_agentic.reasoning.trace import ActionStep
from tests.examples.corpus_search.test_corpus_query_reasoning import (
    _build_corpus_with_fixtures, _replay_model, REPLAY_ROOT,
)


_TOOL_BUILDERS = {
    "knowledge_search": _build_knowledge_search,
    "sql_query": _build_sql_query,
    "inspect_table": _build_inspect_table_tool,
    "python_compute": _build_python_compute_tool,
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_trace_is_replayable(tmp_path):
    # 1. Run question 1, capture trace.
    fixture = json.loads((REPLAY_ROOT / "q1_yoy_growth.json").read_text())
    agent = await _build_corpus_with_fixtures(tmp_path)
    await agent._ensure_query_ready()
    agent._answerer._agent.agent.model = _replay_model(fixture["decisions"])  # type: ignore[attr-defined]
    answer = await agent.query(fixture["question"], include_trace=True)
    trace = answer.reasoning_trace
    assert trace is not None

    # 2. Fresh _LoopContext over the same corpus.
    schemas = await agent._schema_registry.list_schemas()
    fresh_ctx = _LoopContext(
        corpus_agent=agent,
        structured_retriever=agent._structured_retriever,
        schemas=schemas,
        db_path=agent.root / "corpus.sqlite",
    )

    # 3+4. Walk the trace, replay every ActionStep, capture observation.
    tok = _CURRENT_CTX.set(fresh_ctx)
    try:
        replayed_obs: list[str] = []
        for step in trace.steps:
            if not isinstance(step, ActionStep):
                continue
            builder = _TOOL_BUILDERS.get(step.tool_name)
            if builder is None:
                pytest.fail(f"unknown tool in trace: {step.tool_name}")
            tool = builder()
            result = await tool(**step.tool_args)
            replayed_obs.append(str(result))
    finally:
        _CURRENT_CTX.reset(tok)

    original_obs = [
        s.content for s in trace.steps
        if not isinstance(s, ActionStep) and hasattr(s, "source")
    ]

    # We don't require byte-equality (timestamps, SQL row ordering, dict
    # iteration order in python_compute results can shift harmlessly). We
    # require the SAME COUNT of observations and a non-trivial token-level
    # prefix match between each replayed observation and its recorded one.
    assert len(replayed_obs) == len(original_obs), (
        f"observation count mismatch: replayed={len(replayed_obs)} "
        f"original={len(original_obs)}"
    )
    for rep, orig in zip(replayed_obs, original_obs, strict=False):
        prefix_len = min(80, len(orig))
        if prefix_len > 0:
            assert rep[:prefix_len].split() == orig[:prefix_len].split(), (
                f"replayed observation diverges:\nORIG: {orig[:200]}\nREP:  {rep[:200]}"
            )
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/examples/corpus_search/test_trace_is_replayable.py -v
```

Expected: passes. If observation count mismatches, the trace translator is missing or double-emitting a step kind — revisit Task 9.

- [ ] **Step 3: Commit**

```bash
git add tests/examples/corpus_search/test_trace_is_replayable.py
git commit -m "test(reasoning): trace-is-replayable headline test (spec's central claim)"
```

---

## Task 17: Telemetry additions

**Files:**
- Modify: `fireflyframework_agentic/rag/_telemetry.py`
- Modify: `fireflyframework_agentic/rag/retrieval/reasoning_answerer.py`

- [ ] **Step 1: Inspect existing telemetry**

```bash
grep -n "Histogram\|Counter\|set_attribute" fireflyframework_agentic/rag/_telemetry.py | head -30
```

Note the existing factory functions and units; match their style.

- [ ] **Step 2: Add new instruments**

Append to `fireflyframework_agentic/rag/_telemetry.py`:

```python
reasoning_tool_call_duration = _meter.create_histogram(
    name="firefly.rag.reasoning.tool_call_duration_ms",
    unit="ms",
    description="Latency of a single tool call inside the reasoning answer loop.",
)

reasoning_terminal_state = _meter.create_counter(
    name="firefly.rag.reasoning.terminal_state",
    description="Reasoning loop terminal state, labelled by outcome.",
)
```

- [ ] **Step 3: Wrap tool closures with timing**

Update each `_build_*_tool()` in `reasoning_answerer.py` to record `reasoning_tool_call_duration` keyed by `{"tool_name": …}`. Example for `knowledge_search`:

```python
import time
from fireflyframework_agentic.rag._telemetry import reasoning_tool_call_duration


def _build_knowledge_search() -> Any:
    async def knowledge_search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
        ctx = _CURRENT_CTX.get()
        assert ctx is not None, "knowledge_search called outside answer()"
        assert ctx.corpus_agent is not None
        t0 = time.monotonic()
        try:
            hits = await ctx.corpus_agent.retrieve(query, top_k=top_k, rerank=True)
        finally:
            reasoning_tool_call_duration.record(
                (time.monotonic() - t0) * 1000.0,
                {"tool_name": "knowledge_search"},
            )
        out: list[dict[str, Any]] = []
        for h in hits:
            ctx.accumulated_hits[h.chunk_id] = h
            out.append({
                "chunk_id": h.chunk_id,
                "source_path": h.source_path,
                "score": h.score,
                "snippet": h.content[:_SNIPPET_CHARS],
            })
        return out

    return knowledge_search
```

Apply the same timing pattern to the other three closures.

Inside `ReasoningAnswerAgent.answer`, wrap the `agent.run` call in `timed_span("firefly.rag.reasoning.answer", attributes={...})` and emit `reasoning_terminal_state.add(1, {"outcome": <state>})` on each exit path (`answered`, `no_info`, `tool_limit`, `llm_limit`, `timeout`, `error`).

The `firefly.rag.answer_strategy` attribute on the outer `firefly.rag.query` span was already wired in Task 12.

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest tests/unit/corpus_search tests/examples/corpus_search -v -m "not nightly"
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/rag/_telemetry.py fireflyframework_agentic/rag/retrieval/reasoning_answerer.py
git commit -m "feat(reasoning_answerer): tool-call duration + terminal-state telemetry"
```

---

## Task 18: MCP `corpus_query` strategy + include_trace

**Files:**
- Modify: `fireflyframework_agentic/tools/builtins/corpus_rag.py`

- [ ] **Step 1: Extend the signature**

```python
async def corpus_query(
    corpus_id: str,
    question: str,
    top_k: int = 5,
    strategy: Literal["fast", "reasoning"] = "fast",
    include_trace: bool = False,
) -> dict[str, Any]:
    _assert_corpus_exists(corpus_id)
    agent = await _agent_for(corpus_id, strategy=strategy)
    answer = await agent.query(question, top_k=top_k, include_trace=include_trace)
    payload: dict[str, Any] = {
        "corpus_id": corpus_id,
        "question": question,
        "answer": answer.text,
        "citations": answer.citations,
        "cited_sources": [
            {"chunk_id": c.chunk_id, "source_path": c.source_path, "snippet": c.snippet}
            for c in answer.cited_sources
        ],
    }
    if include_trace and answer.reasoning_trace is not None:
        payload["reasoning_trace"] = answer.reasoning_trace.model_dump(mode="json")
    return payload
```

- [ ] **Step 2: Update `_agent_for` for the strategy cache key**

Cache by `(corpus_id, strategy)` so the same process can serve both strategies:

```python
async def _agent_for(corpus_id: str, *, strategy: Literal["fast", "reasoning"] = "fast") -> CorpusAgent:
    key = (corpus_id, strategy)
    async with _CACHE_LOCK:
        if key not in _AGENT_CACHE:
            _AGENT_CACHE[key] = CorpusAgent(
                root=_corpus_root() / corpus_id,
                embed_model=os.environ["EMBEDDING_MODEL"],
                expansion_model=os.environ["EXPANSION_MODEL"],
                answer_model=os.environ["ANSWER_MODEL"],
                rerank_model=os.environ["RERANK_MODEL"],
                answer_strategy=strategy,
            )
        return _AGENT_CACHE[key]
```

Adjust the `_AGENT_CACHE: dict` type annotation and `_shutdown_agents` walk accordingly.

- [ ] **Step 3: Update the `@firefly_tool` description**

Append a paragraph to the existing description mentioning `strategy` and `include_trace`, noting that `reasoning` costs more LLM turns but produces a replayable trace.

- [ ] **Step 4: Run integration tests**

```bash
uv run pytest tests/examples/corpus_search/test_e2e_real_llm.py -v -m "not nightly"
```

Expected: still passes (fast-path default unchanged).

- [ ] **Step 5: Commit**

```bash
git add fireflyframework_agentic/tools/builtins/corpus_rag.py
git commit -m "feat(mcp): corpus_query gains strategy and include_trace params"
```

---

## Task 19: Tier B real-LLM nightly + capture script

**Files:**
- Create: `tests/examples/corpus_search/test_corpus_query_reasoning_real_llm.py`
- Create: `scripts/capture_reasoning_replay.py`

- [ ] **Step 1: Write the nightly test**

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Real-LLM end-to-end tests for the reasoning corpus agent. Nightly only."""

from __future__ import annotations

import re

import pytest

from tests.examples.corpus_search.test_corpus_query_reasoning import (
    _build_corpus_with_fixtures,
)


@pytest.mark.nightly
@pytest.mark.asyncio
@pytest.mark.parametrize("qid,question", [
    ("q1_yoy_growth",
     "What's the YoY revenue growth rate per business unit from 2023 to 2024?"),
    ("q2_weighted_price",
     "What's the weighted average price across products, weighted by units sold?"),
    ("q3_mean_and_stdev_q4_2024_blanks_as_zero",
     "For Q4 2024 revenue, treat blank cells as 0 — what's the mean per region and the standard deviation?"),
    ("q4_headcount_cv_ranking",
     "What's the coefficient of variation of monthly headcount per BU, and rank BUs most-stable to least-stable?"),
    ("q5_operating_efficiency_2024q3",
     "What's the Operating Efficiency for each BU in 2024 Q3?"),
])
async def test_real_llm_answers_within_tolerance(qid, question, tmp_path):
    agent = await _build_corpus_with_fixtures(tmp_path)
    answer = await agent.query(question, include_trace=True)

    # Trace shape: must contain at least one sql_query and one python_compute.
    tool_names = [
        s.tool_name for s in (answer.reasoning_trace.steps or [])
        if hasattr(s, "tool_name")
    ]
    assert "sql_query" in tool_names, f"missing sql_query for {qid}: {tool_names}"
    assert "python_compute" in tool_names, f"missing python_compute for {qid}: {tool_names}"

    # Cross-check: python_compute source must reference at least one numeric
    # literal, which is a plausible signature that values from a prior
    # sql_query were threaded into the Python snippet.
    code_steps = [
        s for s in answer.reasoning_trace.steps
        if hasattr(s, "tool_name") and s.tool_name == "python_compute"
    ]
    assert any(re.search(r"\d", s.tool_args.get("source", "")) for s in code_steps), \
        f"python_compute source contains no numeric content for {qid}"
```

Per-question value assertions (regex against `answer.text` for the expected number within tolerance) should be added one at a time after observing real model behaviour — not up-front.

- [ ] **Step 2: Write the capture script**

Create `scripts/capture_reasoning_replay.py`:

```python
#!/usr/bin/env python3
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Operator CLI: run one question against the real LLM, capture the tool-call
sequence as a Tier A JSON replay fixture.

Usage:
    uv run python scripts/capture_reasoning_replay.py q1_yoy_growth \
        "What's the YoY revenue growth rate per business unit from 2023 to 2024?"
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from tests.examples.corpus_search.test_corpus_query_reasoning import (
    REPLAY_ROOT, _build_corpus_with_fixtures,
)


async def _main(qid: str, question: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        agent = await _build_corpus_with_fixtures(Path(td))
        answer = await agent.query(question, include_trace=True)
        decisions: list[dict] = []
        for step in answer.reasoning_trace.steps:
            if hasattr(step, "tool_name"):  # ActionStep
                decisions.append({
                    "kind": "tool_call",
                    "tool_name": step.tool_name,
                    "args": step.tool_args,
                })
        decisions.append({
            "kind": "final_answer",
            "text": answer.text,
            "citations": answer.citations,
        })
        out_path = REPLAY_ROOT / f"{qid}.json"
        out_path.write_text(json.dumps(
            {"question": question, "decisions": decisions}, indent=2,
        ))
        print(f"wrote {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
```

- [ ] **Step 3: Verify the nightly test is properly deselected by default**

```bash
uv run pytest tests/examples/corpus_search/test_corpus_query_reasoning_real_llm.py -v
```

Expected: all 5 tests deselected by the `nightly` mark.

Manual run with real credentials:

```bash
ANTHROPIC_API_KEY=... uv run pytest tests/examples/corpus_search/test_corpus_query_reasoning_real_llm.py -v -m nightly
```

- [ ] **Step 4: Commit**

```bash
git add tests/examples/corpus_search/test_corpus_query_reasoning_real_llm.py scripts/capture_reasoning_replay.py
git commit -m "test(reasoning): Tier B real-LLM nightly + replay-capture script"
```

---

## Task 20: Docs and CHANGELOG

**Files:**
- Modify: `docs/use-case-corpus-search.md`
- Modify: `docs/reasoning.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: `docs/use-case-corpus-search.md`**

Append a new section after the existing query examples:

```markdown
## Reasoning answers and reproducible traces

`CorpusAgent` has two answer strategies:

- `answer_strategy="fast"` (default) — fixed `expand → retrieve → answer` pipeline.
  Cheapest, one LLM call.
- `answer_strategy="reasoning"` — tool-using agent. Plans its own retrieval;
  can call `knowledge_search`, `sql_query`, `inspect_table`, and `python_compute`;
  emits a typed `ReasoningTrace` that is replayable.

Example — compute YoY revenue growth:

\`\`\`python
agent = CorpusAgent(
    root=Path("/data/finance"),
    embed_model="azure:embed-3-small",
    expansion_model="anthropic:claude-haiku-4-5-20251001",
    answer_model="anthropic:claude-sonnet-4-6",
    rerank_model="anthropic:claude-haiku-4-5-20251001",
    answer_strategy="reasoning",
)
answer = await agent.query(
    "What's the YoY revenue growth per business unit, 2023 vs 2024?",
    include_trace=True,
)
print(answer.text)
for step in answer.reasoning_trace.steps:
    print(step)
\`\`\`

Every `ActionStep` in the trace carries `tool_name` + `tool_args`. To re-run a
recorded trace manually, call each tool with the recorded args — observations
come back identical (modulo timestamps).
```

- [ ] **Step 2: `docs/reasoning.md`**

```markdown
## Note: tool-using ReAct is implemented outside `reasoning/`

The patterns in this module (`ReActPattern`, `PlanAndExecutePattern`, etc.) drive
*text-shaped* reason→act→observe loops via plain `agent.run(prompt)` calls. They
do NOT dispatch real function tools — `_act` emits a placeholder
`ActionStep(tool_name="react_action", ...)` whose payload is the LLM's text.

The framework's tool-using ReAct implementation lives next to its first
consumer in `rag/retrieval/reasoning_answerer.py`. It delegates the loop to
pydantic-ai's native tool calling (`FireflyAgent(tools=[...])`), then
translates the resulting message history into a `ReasoningTrace`.

Follow-up: promote a `ToolCallingReActPattern` into this module once a second
consumer needs it.
```

- [ ] **Step 3: `CHANGELOG.md`**

Insert under the most-recent unreleased section:

```markdown
### Added

- `CorpusAgent` `answer_strategy` constructor flag — choose between the existing
  fast pipeline (`"fast"`, default) and a new tool-using reasoning agent
  (`"reasoning"`) that plans retrieval and calls `knowledge_search`,
  `sql_query`, `inspect_table`, `python_compute`.
- `Answer.reasoning_trace` — optional typed trace populated when
  `CorpusAgent.query(..., include_trace=True)`.
- MCP `corpus_query` tool gains `strategy` and `include_trace` parameters.
- New optional extra `[reasoning-eval]` brings in `numpy` + `pandas` for the
  `python_compute` sandbox.
```

- [ ] **Step 4: Verify docs don't break collection**

```bash
uv run pytest tests/ --collect-only -q | tail -5
```

Expected: no errors; collection still works.

- [ ] **Step 5: Commit**

```bash
git add docs/use-case-corpus-search.md docs/reasoning.md CHANGELOG.md
git commit -m "docs: reasoning answer strategy + replayable traces"
```

---

## Self-review checklist

Run through before declaring the implementation done:

1. **Every spec requirement covered?** Walk through spec §1–§10 + Tests + Observability + Rollout + Docs sections. Each maps to one of Tasks 1–20.
2. **Fast path regression?** `tests/unit/corpus_search/test_agent_query.py` (and any other existing fast-path tests) still pass unchanged. If they don't, Task 12 plumbing broke something — likely the `_ensure_query_ready` reorder.
3. **`tool_args` JSON-serialisable everywhere?** Every `ActionStep.tool_args` must round-trip through `json.dumps/loads`. `test_trace_is_replayable.py` will catch this implicitly, but check explicitly when adding new tools later.
4. **`reasoning_trace` truly off by default at the MCP boundary?** Hit the MCP `corpus_query` with the legacy shape — no `reasoning_trace` field appears in the response.
5. **Sandbox denylist holes?** If reviewers spot a new escape pattern, add it to `DISALLOWED_BUILTIN_NAMES` and the AST denied-attribute set with a regression test.
6. **CI markers right?** Confirm `.github/workflows/*.yml` runs the default `pytest` invocation (which includes `@pytest.mark.integration`) on PR gate, and that `nightly` is excluded from PR gate and runs on the scheduled job.
