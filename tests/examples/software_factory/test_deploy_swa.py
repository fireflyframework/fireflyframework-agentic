# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the Bicep and Crossplane SWA deployment targets."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from software_factory.deploy.base import DeployError, InfraSpec
from software_factory.deploy.bicep import BicepSWATarget
from software_factory.deploy.crossplane import CrossplaneSWATarget


# ---------------------------------------------------------------------------
# BicepSWATarget
# ---------------------------------------------------------------------------

def test_bicep_provider_name() -> None:
    t = BicepSWATarget(app_name="myapp", resource_group="myrg")
    assert t.provider == "azure-bicep"


def test_bicep_render_produces_bicep_spec(tmp_path: Path) -> None:
    t = BicepSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="staging")
    assert spec.format == "bicep"
    assert "Microsoft.Web/staticSites" in spec.content
    assert spec.parameters["appName"] == "myapp"
    assert spec.parameters["environment"] == "staging"
    assert spec.source_template == "BicepSWATarget"


def test_bicep_render_content_is_valid_bicep(tmp_path: Path) -> None:
    t = BicepSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="production")
    assert "param appName string" in spec.content
    assert "output url string" in spec.content


def test_bicep_apply_calls_az_deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        captured.append(cmd)
        payload = '{"properties": {"outputs": {"url": {"value": "https://myapp.azurestaticapps.net"}}}}'
        return 0, payload, ""

    monkeypatch.setattr("software_factory.deploy.bicep._run", fake_run)

    t = BicepSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="production")

    async def no_smoke(result: object) -> bool:
        return True

    monkeypatch.setattr(t, "smoke_test", no_smoke)
    result = asyncio.run(t.apply(spec))

    assert result.url == "https://myapp.azurestaticapps.net"
    assert any("az" in c[0] and "deployment" in c for c in captured)


def test_bicep_apply_raises_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "ERROR: deployment failed"

    monkeypatch.setattr("software_factory.deploy.bicep._run", fake_run)

    t = BicepSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="production")
    with pytest.raises(DeployError, match="az deployment failed"):
        asyncio.run(t.apply(spec))


# ---------------------------------------------------------------------------
# CrossplaneSWATarget
# ---------------------------------------------------------------------------

def test_crossplane_provider_name() -> None:
    t = CrossplaneSWATarget(app_name="myapp", resource_group="myrg")
    assert t.provider == "crossplane"


def test_crossplane_render_produces_xr_manifest(tmp_path: Path) -> None:
    t = CrossplaneSWATarget(app_name="myapp", resource_group="myrg", location="eastus")
    spec = t.render(tmp_path, environment="staging")
    assert spec.format == "crossplane"
    assert "StaticWebApp" in spec.content
    assert "myapp" in spec.content
    assert "eastus" in spec.content
    assert spec.source_template == "CrossplaneSWATarget"


def test_crossplane_render_is_valid_yaml(tmp_path: Path) -> None:
    import yaml  # noqa: PLC0415 — intentional: yaml is a test-only dep here
    t = CrossplaneSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="production")
    parsed = yaml.safe_load(spec.content)
    assert parsed["kind"] == "StaticWebApp"
    assert parsed["metadata"]["name"] == "myapp"


def test_crossplane_apply_calls_kubectl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []
    call_count = 0

    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal call_count
        captured.append(cmd)
        call_count += 1
        if "wait" in cmd:
            return 0, "", ""
        if "jsonpath" in " ".join(cmd):
            return 0, "myapp.azurestaticapps.net\n", ""
        return 0, "", ""

    monkeypatch.setattr("software_factory.deploy.crossplane._run", fake_run)

    t = CrossplaneSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="production")

    async def no_smoke(result: object) -> bool:
        return True

    monkeypatch.setattr(t, "smoke_test", no_smoke)
    result = asyncio.run(t.apply(spec))

    assert result.url == "https://myapp.azurestaticapps.net"
    assert any("apply" in c for c in captured)


def test_crossplane_apply_raises_on_kubectl_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "Error: connection refused"

    monkeypatch.setattr("software_factory.deploy.crossplane._run", fake_run)

    t = CrossplaneSWATarget(app_name="myapp", resource_group="myrg")
    spec = t.render(tmp_path, environment="production")
    with pytest.raises(DeployError, match="kubectl apply failed"):
        asyncio.run(t.apply(spec))
