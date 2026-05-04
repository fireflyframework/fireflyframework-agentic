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

"""Smoke import test for the factory action_runtime package."""

from __future__ import annotations

import fireflyframework_agentic.factory.action_runtime as rt
from fireflyframework_agentic.factory.action_runtime.exceptions import (
    ActionInputError,
    ActionRuntimeError,
    MissingArtifactError,
)
from fireflyframework_agentic.factory.action_runtime.io_models import RunResult


def test_action_runtime_package_imports() -> None:
    assert rt is not None


def test_exceptions_import() -> None:
    assert issubclass(MissingArtifactError, ActionRuntimeError)
    assert MissingArtifactError.exit_code == 78
    assert ActionInputError.exit_code == 1


def test_run_result_model() -> None:
    r = RunResult(agent="product_owner", outputs={"pr_number": "42"}, cost_usd=0.1, tokens_in=10, tokens_out=20)
    assert r.agent == "product_owner"
    assert r.outputs == {"pr_number": "42"}
