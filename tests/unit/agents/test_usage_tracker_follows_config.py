"""The installed configuration reaches the process usage tracker, and an agent may own a ledger.

``default_usage_tracker`` is built when ``observability.usage`` is imported, from whatever
``get_config()`` answered at that moment — and ``agents.base`` imports it, so by the time any
host has ``from fireflyframework_agentic.agents.base import FireflyAgent`` at module top the
tracker exists with the framework defaults. ``set_config()`` then installed a new instance that
the tracker never read: its ``usage_tracker_max_records`` and ``budget_limit_usd`` were honoured
by nothing. The contract pinned here: installing a config reconfigures the process tracker in
place (the same object every ``patch("...agents.base.default_usage_tracker")`` and every
``get_summary()`` in the docs refers to), and an agent given a ``usage_tracker`` of its own
records there instead of the process ledger — the per-tenant ledger a multi-tenant host needs.
"""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from fireflyframework_agentic.agents.base import FireflyAgent
from fireflyframework_agentic.config import FireflyAgenticConfig, reset_config, set_config
from fireflyframework_agentic.observability.budget import BudgetExceededError
from fireflyframework_agentic.observability.usage import UsageRecord, UsageTracker, default_usage_tracker


def _record(cost: float) -> UsageRecord:
    return UsageRecord(agent="a", model="m", input_tokens=1, output_tokens=1, total_tokens=2, cost_usd=cost)


@pytest.fixture(autouse=True)
def _clean_config() -> None:  # type: ignore[misc]
    reset_config()
    default_usage_tracker.reset()
    yield  # type: ignore[misc]
    reset_config()
    default_usage_tracker.reset()


class TestSetConfigReachesTheProcessTracker:
    def test_max_records_is_applied_to_the_tracker_agents_base_already_imported(self) -> None:
        set_config(FireflyAgenticConfig(usage_tracker_max_records=1))
        assert default_usage_tracker.max_records == 1
        default_usage_tracker.record(_record(0.0))
        default_usage_tracker.record(_record(0.0))
        assert default_usage_tracker.get_summary().record_count == 1

    def test_a_smaller_cap_trims_what_is_already_kept(self) -> None:
        for _ in range(5):
            default_usage_tracker.record(_record(0.0))
        set_config(FireflyAgenticConfig(usage_tracker_max_records=2))
        assert default_usage_tracker.get_summary().record_count == 2

    def test_the_budget_limit_is_applied_to_the_tracker(self) -> None:
        set_config(FireflyAgenticConfig(budget_limit_usd=0.01))
        default_usage_tracker.record(_record(0.009))
        with pytest.raises(BudgetExceededError):
            default_usage_tracker.record(_record(0.009))

    def test_reset_config_restores_the_defaults(self) -> None:
        set_config(FireflyAgenticConfig(usage_tracker_max_records=1, budget_limit_usd=0.01))
        reset_config()
        assert default_usage_tracker.max_records == 10_000
        default_usage_tracker.record(_record(5.0))  # no gate any more

    def test_install_reads_the_installed_instance_not_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIREFLY_AGENTIC_USAGE_TRACKER_MAX_RECORDS", "7")
        set_config(FireflyAgenticConfig(usage_tracker_max_records=3))
        assert default_usage_tracker.max_records == 3


def _answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("ok")])


class TestAnAgentMayOwnItsLedger:
    async def test_an_agent_given_a_tracker_records_there_and_not_in_the_process_ledger(self) -> None:
        own = UsageTracker(sinks=[], max_records=5)
        cfg = FireflyAgenticConfig(default_model="test", cost_tracking_enabled=True, observability_enabled=False)
        agent = FireflyAgent(
            "tenant-a", model=FunctionModel(_answer), config=cfg, usage_tracker=own, auto_register=False
        )
        assert agent.usage_tracker is own
        await agent.run("hello")
        assert own.get_summary().record_count == 1
        assert default_usage_tracker.get_summary().record_count == 0

    async def test_without_a_tracker_of_its_own_the_agent_records_in_the_process_ledger(self) -> None:
        cfg = FireflyAgenticConfig(default_model="test", cost_tracking_enabled=True, observability_enabled=False)
        agent = FireflyAgent("shared", model=FunctionModel(_answer), config=cfg, auto_register=False)
        assert agent.usage_tracker is default_usage_tracker
        await agent.run("hello")
        assert default_usage_tracker.get_summary().record_count == 1

    async def test_an_agent_config_budget_is_enforced_on_its_own_ledger(self) -> None:
        """``FireflyAgent(config=FireflyAgenticConfig(budget_limit_usd=...))`` without a tracker
        of its own cannot resize the process ledger — that is what ``set_config`` is for — but
        with ``usage_tracker=UsageTracker.for_config(cfg)`` the agent's config governs its ledger."""
        cfg = FireflyAgenticConfig(
            default_model="test", cost_tracking_enabled=True, observability_enabled=False, usage_tracker_max_records=1
        )
        own = UsageTracker.for_config(cfg, sinks=[])
        assert own.max_records == 1
        agent = FireflyAgent("capped", model=FunctionModel(_answer), config=cfg, usage_tracker=own, auto_register=False)
        await agent.run("one")
        await agent.run("two")
        assert own.get_summary().record_count == 1
