"""Tests for plugin.py."""

from __future__ import annotations

from fireflyframework_agentic.plugin import (
    DiscoveredPlugin,
    DiscoveryResult,
    PluginDiscovery,
)


class TestDiscoveredPlugin:
    def test_fields(self) -> None:
        p = DiscoveredPlugin(group="test", name="my-plugin", value="mod:obj")
        assert p.group == "test"
        assert p.name == "my-plugin"
        assert p.loaded_object is None
        assert p.error is None


class TestDiscoveryResult:
    def test_successful_and_failed(self) -> None:
        ok = DiscoveredPlugin(group="g", name="ok", value="v", loaded_object=object())
        bad = DiscoveredPlugin(group="g", name="bad", value="v", error="ImportError")
        result = DiscoveryResult(plugins=[ok, bad])
        assert len(result.successful) == 1
        assert len(result.failed) == 1


class TestPluginDiscovery:
    def test_discover_group_returns_list(self) -> None:
        # No actual plugins installed, but the API should work
        results = PluginDiscovery.discover_group("fireflyframework_agentic.agents")
        assert isinstance(results, list)

    def test_discover_all_returns_result(self) -> None:
        result = PluginDiscovery.discover_all()
        assert isinstance(result, DiscoveryResult)
