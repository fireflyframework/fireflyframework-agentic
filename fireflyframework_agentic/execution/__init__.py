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

"""Secure script execution -- run untrusted/generated Python in a sandbox.

One :class:`ExecutionEnvironment` abstraction with tiered, deny-by-default
backends. The default :class:`MontyEnvironment` (Rust micro-interpreter, no
FS/network/env; host access only via explicitly registered external functions)
covers glue logic over Firefly tools. :class:`SecureScriptRunner` adds the
static safety pre-screen and the generate -> validate -> execute -> capture loop;
:func:`toolkit_external_functions` powers Firefly Code Mode.

    from fireflyframework_agentic.execution import MontyEnvironment, SecureScriptRunner

    runner = SecureScriptRunner(MontyEnvironment())
    result = await runner.execute("a = 2\\nb = 3\\na * b")   # -> ExecutionResult(success=True, output=6)

The Monty backend requires the ``script-execution`` extra.
"""

from fireflyframework_agentic.execution.code_mode import toolkit_external_functions
from fireflyframework_agentic.execution.environment import ExecutionEnvironment
from fireflyframework_agentic.execution.monty_env import MontyEnvironment
from fireflyframework_agentic.execution.runner import SecureScriptRunner
from fireflyframework_agentic.execution.safety import (
    CodeViolation,
    SafetyPolicy,
    SafetyReport,
    analyze_code,
)
from fireflyframework_agentic.execution.types import (
    Capability,
    ExecutionLimits,
    ExecutionResult,
)

__all__ = [
    "Capability",
    "CodeViolation",
    "ExecutionEnvironment",
    "ExecutionLimits",
    "ExecutionResult",
    "MontyEnvironment",
    "SafetyPolicy",
    "SafetyReport",
    "SecureScriptRunner",
    "analyze_code",
    "toolkit_external_functions",
]
