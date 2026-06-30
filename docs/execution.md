# Secure Script Execution

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

`fireflyframework_agentic.execution` runs **untrusted or model-generated Python**
in a sandbox, on *your* infrastructure. It is built around a single
`ExecutionEnvironment` abstraction with tiered, deny-by-default backends, and a
`generate → validate → execute → capture` loop that reuses Firefly's existing
guard and audit machinery.

> **Why not just use the provider's code tool?** pydantic-ai's built-in code
> execution runs server-side in the *model provider's* sandbox — you get zero
> control over what executes on your own infrastructure. Use it for "let the
> model run throwaway analysis", but for self-hosted, audited execution use this
> subsystem. (Historical note: `mcp-run-python` was archived by its maintainers
> as unsafe for untrusted code, and `RestrictedPython` is explicitly *not* a
> sandbox — Firefly uses neither as a boundary.)

The Monty backend requires the extra:

```bash
pip install 'fireflyframework-agentic[script-execution]'
```

---

## Quick start

```python
from fireflyframework_agentic.execution import MontyEnvironment, SecureScriptRunner

runner = SecureScriptRunner(MontyEnvironment())

result = await runner.execute("a = 2\nb = 3\na * b")
assert result.success and result.output == 6

# Dangerous code is rejected by the static pre-screen — the sandbox never runs it:
bad = await runner.execute("import os\nos.system('rm -rf /')")
assert bad.success is False
assert bad.error_type == "CodeSafetyError"
```

`ExecutionResult` carries `success`, `output` (the script's final expression),
`stdout`/`stderr`, and on failure `error` / `error_type` / `violations`.

---

## The execution environment

```python
class ExecutionEnvironment(Protocol):
    @property
    def capabilities(self) -> frozenset[Capability]: ...
    async def run_code(self, code, *, inputs=None,
                       external_functions=None, limits=None) -> ExecutionResult: ...
```

Environments are **deny-by-default**: the only host access guest code gets is
the set of `external_functions` you hand to that specific call.

### `MontyEnvironment` (tiers 0–1, default)

[Monty](https://pypi.org/project/pydantic-monty/) is a Rust micro-interpreter
with a deny-by-default capability model (no filesystem, network, or environment;
host access only through registered external functions), resource limits, and
microsecond startup. It executes a Python *subset* (no third-party packages) —
perfect for glue logic over Firefly tools, not for `pandas` jobs.

| Tier | What | Use |
|---|---|---|
| 0 | Monty, no external functions | Pure computation. |
| 1 | Monty + allow-listed `external_functions` | Firefly **Code Mode** — scripts call your tools. |

> Higher tiers — full-CPython Docker (gVisor/Kata) and cloud micro-VMs
> (E2B/Modal) for third-party-package, network, or GPU workloads — slot behind
> the same `ExecutionEnvironment` interface as later additions.

---

## Resource limits

```python
from fireflyframework_agentic.execution import ExecutionLimits

await env.run_code(code, limits=ExecutionLimits(
    timeout_seconds=5.0,        # wall-clock cap — the reliable runaway-loop guard
    max_memory_bytes=64 * 1024 * 1024,
    max_allocations=1_000_000,
    max_recursion_depth=500,
))
```

`MontyEnvironment` applies a **30-second wall-clock default** as a runaway-loop
safety net; per-call `limits` are merged over it field-by-field.

---

## Static safety pre-screen

`analyze_code` is an AST check applied *before* code reaches the interpreter. It
is **defense in depth, not the boundary** — the sandbox is the boundary — but it
gives fast, legible rejections and a second layer of protection.

```python
from fireflyframework_agentic.execution import analyze_code, SafetyPolicy

report = analyze_code("().__class__.__bases__[0].__subclasses__()")
assert not report.safe  # dunder-walk escape attempt

# Tighten or relax the policy:
policy = SafetyPolicy(allowed_modules=frozenset({"math", "statistics"}))
```

It rejects dangerous imports (`os`, `subprocess`, `socket`, …), dynamic-execution
builtins (`eval`, `exec`, `__import__`, `open`, …), and dunder attribute walks.

---

## Code Mode: tools as external functions

Instead of one tool call per step, let the model emit a *script* that
orchestrates several tools at once — executed in the sandbox with those tools
registered as external functions. This cuts model round-trips while keeping every
host call audited and capability-gated.

```python
from fireflyframework_agentic.execution import toolkit_external_functions

funcs = toolkit_external_functions(my_toolkit)          # {tool_name: callable}
result = await runner.execute(
    "totals = fetch_orders(customer_id)\nsummarize(totals)",
    inputs={"customer_id": 42},
    external_functions=funcs,
)
```

Positional arguments in the script are mapped onto each tool's declared parameter
names; async tools are awaited automatically.

---

## Redacting captured output

Captured `stdout` can be scrubbed before results re-enter a model's context —
wire the security layer's `OutputGuard` here:

```python
from fireflyframework_agentic.security import default_output_guard

runner = SecureScriptRunner(
    MontyEnvironment(),
    output_scrubber=lambda s: default_output_guard.scan(s).sanitised_output or s,
)
```

---

## API reference

| Symbol | Purpose |
|---|---|
| `ExecutionEnvironment` | Protocol over sandbox backends. |
| `MontyEnvironment` | Default deny-by-default Monty backend (tiers 0–1). |
| `SecureScriptRunner` | validate → execute → capture orchestrator. |
| `analyze_code` / `SafetyPolicy` / `SafetyReport` / `CodeViolation` | Static AST pre-screen. |
| `ExecutionLimits` | Per-run resource ceilings. |
| `ExecutionResult` | Outcome (`success`, `output`, `stdout`, `stderr`, `error`, `violations`). |
| `Capability` | Capabilities an environment grants (`COMPUTE`, `EXTERNAL_FUNCTIONS`, …). |
| `toolkit_external_functions` | Build a Code Mode external-function map from tools. |

Exceptions live in `fireflyframework_agentic.exceptions`: `ExecutionError` (base),
`CodeSafetyError`, `SandboxUnavailableError`.
