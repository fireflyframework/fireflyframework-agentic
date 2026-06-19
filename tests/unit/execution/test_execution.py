# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the secure script-execution subsystem (SP-6).

Safety / runner / code-mode tests use a fake environment and need no native
dependency. The Monty-backed tests are skipped when the ``script-execution``
extra (``pydantic-monty``) is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from fireflyframework_agentic.execution import (
    Capability,
    ExecutionLimits,
    ExecutionResult,
    SafetyPolicy,
    SecureScriptRunner,
    analyze_code,
    toolkit_external_functions,
)

# -- static safety pre-screen ------------------------------------------------


class TestAnalyzeCode:
    @pytest.mark.parametrize(
        "code",
        [
            "import os\nos.system('rm -rf /')",
            "from subprocess import run\nrun(['ls'])",
            "eval('1+1')",
            "exec('x = 1')",
            "__import__('os')",
            "().__class__.__bases__[0].__subclasses__()",
            "open('/etc/passwd').read()",
        ],
    )
    def test_rejects_dangerous_code(self, code):
        report = analyze_code(code)
        assert not report.safe
        assert report.violations

    @pytest.mark.parametrize(
        "code",
        [
            "a = 2\nb = 3\na * b",
            "total = sum(range(10))\ntotal",
            "import math\nmath.sqrt(16)",
            "data = {'k': [1, 2, 3]}\nsorted(data['k'], reverse=True)",
        ],
    )
    def test_allows_safe_code(self, code):
        assert analyze_code(code).safe

    def test_syntax_error_is_a_violation(self):
        report = analyze_code("def (:\n  pass")
        assert not report.safe
        assert any("syntax" in m for m in report.messages())

    def test_allowlist_policy(self):
        policy = SafetyPolicy(allowed_modules=frozenset({"math"}))
        assert analyze_code("import math\nmath.pi", policy).safe
        assert not analyze_code("import json\njson.dumps({})", policy).safe

    def test_dunder_access_can_be_permitted(self):
        policy = SafetyPolicy(deny_dunder_access=False)
        assert analyze_code("x = object()\nx.__class__", policy).safe


# -- runner orchestration (fake environment) ---------------------------------


class _FakeEnv:
    """Records calls; returns a canned result."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.COMPUTE})

    async def run_code(self, code, *, inputs=None, external_functions=None, limits=None) -> ExecutionResult:
        self.calls.append({"code": code, "inputs": inputs, "external_functions": external_functions})
        return ExecutionResult(success=True, output="ran", stdout="secret=abc123\n")


@pytest.mark.asyncio
async def test_runner_rejects_unsafe_before_executing():
    env = _FakeEnv()
    runner = SecureScriptRunner(env)
    result = await runner.execute("import os\nos.system('x')")
    assert result.success is False
    assert result.error_type == "CodeSafetyError"
    assert result.violations
    assert env.calls == []  # the sandbox was never invoked


@pytest.mark.asyncio
async def test_runner_runs_safe_code():
    env = _FakeEnv()
    runner = SecureScriptRunner(env)
    result = await runner.execute("a = 1\na + 1", inputs={"a": 1})
    assert result.success and result.output == "ran"
    assert len(env.calls) == 1


@pytest.mark.asyncio
async def test_runner_output_scrubber_redacts_stdout():
    env = _FakeEnv()
    runner = SecureScriptRunner(env, output_scrubber=lambda s: s.replace("abc123", "[REDACTED]"))
    result = await runner.execute("1 + 1")
    assert "abc123" not in result.stdout
    assert "[REDACTED]" in result.stdout


@pytest.mark.asyncio
async def test_runner_skip_safety_bypasses_prescreen():
    env = _FakeEnv()
    runner = SecureScriptRunner(env)
    result = await runner.execute("import os", skip_safety=True)
    assert result.success
    assert len(env.calls) == 1


# -- Code Mode (tool -> external function) -----------------------------------


class _FakeParam:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeTool:
    def __init__(self, name: str, params: list[str]) -> None:
        self.name = name
        self.parameters = [_FakeParam(p) for p in params]
        self.received: dict[str, Any] | None = None

    async def execute(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return f"{self.name}:{sorted(kwargs.items())}"


@pytest.mark.asyncio
async def test_toolkit_external_functions_maps_positional_args():
    tool = _FakeTool("add_numbers", ["x", "y"])
    funcs = toolkit_external_functions([tool])
    assert set(funcs) == {"add_numbers"}
    out = await funcs["add_numbers"](1, 2)  # positional, as guest code would call it
    assert tool.received == {"x": 1, "y": 2}
    assert "add_numbers" in out


def test_toolkit_external_functions_allowlist_and_toolslike():
    class _Kit:
        def __init__(self, tools):
            self._t = tools

        @property
        def tools(self):
            return self._t

    kit = _Kit([_FakeTool("a", []), _FakeTool("b", [])])
    funcs = toolkit_external_functions(kit, names=["a"])
    assert set(funcs) == {"a"}


# -- Monty backend (requires the script-execution extra) ---------------------

pytest.importorskip("pydantic_monty")


def _monty_env():
    from fireflyframework_agentic.execution import MontyEnvironment

    return MontyEnvironment()


@pytest.mark.asyncio
async def test_monty_runs_pure_computation():
    result = await _monty_env().run_code("a = 2\nb = 3\na * b")
    assert result.success
    assert result.output == 6


@pytest.mark.asyncio
async def test_monty_captures_stdout():
    result = await _monty_env().run_code("print('hello sandbox')\n42")
    assert result.success
    assert result.output == 42
    assert "hello sandbox" in result.stdout


@pytest.mark.asyncio
async def test_monty_injects_inputs():
    result = await _monty_env().run_code("n * 10", inputs={"n": 7})
    assert result.success and result.output == 70


@pytest.mark.asyncio
async def test_monty_external_function_call():
    def greet(who: str) -> str:
        return f"hi {who}"

    result = await _monty_env().run_code(
        "greet(name)", inputs={"name": "firefly"}, external_functions={"greet": greet}
    )
    assert result.success and result.output == "hi firefly"


@pytest.mark.asyncio
async def test_monty_runtime_error_is_captured_not_raised():
    result = await _monty_env().run_code("1 / 0")
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_monty_denies_os_access():
    # The sandbox has no real os; resolving a forbidden attribute fails.
    result = await _monty_env().run_code("import os\nos.getcwd()")
    assert result.success is False


@pytest.mark.asyncio
async def test_monty_timeout_stops_runaway_loop():
    env = _monty_env()
    # The wall-clock timeout (-> Monty max_duration_secs) bounds an infinite loop.
    result = await env.run_code(
        "x = 0\nwhile True:\n    x = x + 1\nx",
        limits=ExecutionLimits(timeout_seconds=1.0),
    )
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_secure_runner_end_to_end_with_monty():
    runner = SecureScriptRunner(_monty_env())
    # unsafe is rejected statically
    rejected = await runner.execute("import os\nos.getcwd()")
    assert rejected.error_type == "CodeSafetyError"
    # safe runs in the sandbox
    ok = await runner.execute("sum(range(5))")
    assert ok.success and ok.output == 10
