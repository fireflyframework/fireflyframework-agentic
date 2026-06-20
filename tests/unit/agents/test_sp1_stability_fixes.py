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

"""SP-1 regression tests for three previously-silent stability bugs:

1. OutputGuardMiddleware sanitisation degraded the result to a bare string
   (the ``_replace`` guard never matched the dataclass ``AgentRunResult``).
2. RetryMiddleware was a no-op — its config never reached the retry loop.
3. ``_firefly_cost_usd`` was read but never written, so logged cost was always
   absent.
"""

from __future__ import annotations

import dataclasses
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import (
    OutputGuardMiddleware,
    RetryMiddleware,
    _replace_output,
)
from fireflyframework_agentic.config import reset_config
from fireflyframework_agentic.observability.usage import UsageRecord


@pytest.fixture(autouse=True)
def _reset_cfg():
    reset_config()
    yield
    reset_config()


# --------------------------------------------------------------------------
# Bug 1: output sanitisation must preserve the result object's contract
# --------------------------------------------------------------------------


@dataclasses.dataclass
class _DataclassResult:
    output: str
    token: str = "keep-me"


class _Scan:
    def __init__(self, *, safe: bool, sanitised: str | None = None) -> None:
        self.safe = safe
        self.matched_categories = ["secrets"]
        self.matched_patterns = ["pattern"]
        self.sanitised_output = sanitised
        self.reason = "matched"


class _FakeGuard:
    def __init__(self, scan: _Scan) -> None:
        self._scan = scan

    def scan(self, text: str) -> _Scan:
        return self._scan


class _Ctx:
    agent_name = "agent"


class TestReplaceOutput:
    def test_namedtuple(self):
        nt_type = namedtuple("NT", ["output", "extra"])
        out = _replace_output(nt_type(output="x", extra="y"), "new")
        assert isinstance(out, nt_type)
        assert out.output == "new" and out.extra == "y"

    def test_dataclass(self):
        out = _replace_output(_DataclassResult(output="x"), "new")
        assert isinstance(out, _DataclassResult)
        assert out.output == "new" and out.token == "keep-me"

    def test_plain_mutable_object(self):
        class _P:
            def __init__(self) -> None:
                self.output = "x"
                self.extra = "y"

        p = _P()
        out = _replace_output(p, "new")
        assert out is p and out.output == "new" and out.extra == "y"

    def test_readonly_falls_back_to_bare_value(self):
        class _ReadOnly:
            __slots__ = ()

            @property
            def output(self) -> str:
                return "orig"

        assert _replace_output(_ReadOnly(), "new") == "new"


@pytest.mark.asyncio
async def test_sanitise_preserves_dataclass_result_type():
    mw = OutputGuardMiddleware(guard=_FakeGuard(_Scan(safe=False, sanitised="[REDACTED]")), sanitise=True)
    result = _DataclassResult(output="my secret token is leaking")

    out = await mw.after_run(_Ctx(), result)

    # Regression: previously returned the bare string "[REDACTED]".
    assert isinstance(out, _DataclassResult)
    assert out.output == "[REDACTED]"
    assert out.token == "keep-me"


# --------------------------------------------------------------------------
# Bug 2: RetryMiddleware config must actually reach the retry loop
# --------------------------------------------------------------------------


def _make_429() -> ModelHTTPError:
    return ModelHTTPError(status_code=429, model_name="test", body=None)


@pytest.mark.asyncio
async def test_retry_override_takes_precedence_over_config():
    agent = FireflyAgent("retry-override", model="test", auto_register=False)
    mock_result = MagicMock()
    mock_result.output = "ok"
    agent._agent.run = AsyncMock(side_effect=[_make_429(), _make_429(), mock_result])

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("fireflyframework_agentic.agents.base.get_config") as mock_cfg,
    ):
        cfg = mock_cfg.return_value
        cfg.rate_limit_max_retries = 0  # config alone would give up after the first call
        cfg.rate_limit_base_delay = 0.01
        cfg.rate_limit_max_delay = 0.1
        result = await agent._run_with_rate_limit_retry(
            "hello", retry_override={"max_retries": 2, "base_delay": 0.01, "max_delay": 0.1}
        )

    assert result is mock_result
    assert agent._agent.run.call_count == 3  # override enabled the extra retries


@pytest.mark.asyncio
async def test_retry_middleware_config_flows_into_retry(monkeypatch):
    """RetryMiddleware.before_run config must reach _run_with_rate_limit_retry."""
    agent = FireflyAgent(
        "retry-mw",
        model="test",
        auto_register=False,
        default_middleware=False,
        middleware=[RetryMiddleware(max_retries=7, base_delay=1.5, max_delay=9.0, backoff_multiplier=3.0)],
    )

    captured: dict[str, object] = {}

    async def _fake_retry(prompt, *, deps=None, timeout=None, retry_override=None, **kwargs):
        captured["override"] = retry_override
        r = MagicMock()
        r.output = "done"
        return r

    monkeypatch.setattr(agent, "_run_with_rate_limit_retry", _fake_retry)
    monkeypatch.setattr(agent, "_persist_memory", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_record_usage", lambda *a, **k: None)

    await agent.run("hello")

    assert captured["override"] == {
        "max_retries": 7,
        "base_delay": 1.5,
        "max_delay": 9.0,
        "backoff_multiplier": 3.0,
    }


# --------------------------------------------------------------------------
# Bug 3: cost must be wired onto the result for downstream logging
# --------------------------------------------------------------------------


class _Usage:
    input_tokens = 100
    output_tokens = 50
    requests = 1
    cache_write_tokens = 0
    cache_read_tokens = 0


class _Result:
    def usage(self) -> _Usage:
        return _Usage()


def test_record_usage_sets_firefly_cost_on_result():
    agent = FireflyAgent("cost-attr", model="test", auto_register=False)
    result = _Result()

    with patch("fireflyframework_agentic.agents.base.default_usage_tracker") as tracker:
        tracker.record_call.return_value = UsageRecord(cost_usd=0.0123)
        agent._record_usage(result, 10.0)

    assert result._firefly_cost_usd == 0.0123
