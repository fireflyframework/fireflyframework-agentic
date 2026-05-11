# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for BicepTarget and CrossplaneTarget.

Templates are created inline in tmp_path — the targets are generic and
work with any Bicep or Crossplane content.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from software_factory.deploy.base import DeployError
from software_factory.deploy.bicep import BicepTarget
from software_factory.deploy.crossplane import CrossplaneTarget

_BICEP_TEMPLATE = """\
param location string = 'spaincentral'
param environment string = 'production'

resource swa 'Microsoft.Web/staticSites@2022-09-01' = {
  name: 'myapp'
  location: location
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

output url string = 'https://myapp.azurestaticapps.net'
"""

_CROSSPLANE_MANIFEST = """\
apiVersion: azure.upbound.io/v1beta1
kind: StaticWebApp
metadata:
  name: myapp
spec:
  forProvider:
    location: spaincentral
    resourceGroupName: myrg
  providerConfigRef:
    name: {provider_config}
"""


# ---------------------------------------------------------------------------
# BicepTarget
# ---------------------------------------------------------------------------

def test_bicep_provider_name() -> None:
    assert BicepTarget(resource_group="myrg").provider == "azure-bicep"


def test_bicep_render_from_file(tmp_path: Path) -> None:
    bicep_file = tmp_path / "main.bicep"
    bicep_file.write_text(_BICEP_TEMPLATE)

    t = BicepTarget(resource_group="myrg")
    spec = t.render(bicep_file, environment="staging")

    assert spec.format == "bicep"
    assert "staticSites" in spec.content
    assert spec.parameters["environment"] == "staging"
    assert spec.source_template == str(bicep_file)


def test_bicep_render_from_directory(tmp_path: Path) -> None:
    (tmp_path / "main.bicep").write_text(_BICEP_TEMPLATE)

    t = BicepTarget(resource_group="myrg")
    spec = t.render(tmp_path, environment="production")
    assert "staticSites" in spec.content


def test_bicep_render_extra_parameters_override(tmp_path: Path) -> None:
    (tmp_path / "main.bicep").write_text(_BICEP_TEMPLATE)

    t = BicepTarget(resource_group="myrg", parameters={"sku": "Standard"})
    spec = t.render(tmp_path, environment="production")
    assert spec.parameters["sku"] == "Standard"


def test_bicep_render_raises_when_no_bicep(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="no .bicep template"):
        BicepTarget(resource_group="myrg").render(tmp_path, environment="production")


def test_bicep_render_raises_on_multiple_bicep_files(tmp_path: Path) -> None:
    (tmp_path / "a.bicep").write_text("param x string")
    (tmp_path / "b.bicep").write_text("param y string")
    with pytest.raises(DeployError, match="multiple .bicep files"):
        BicepTarget(resource_group="myrg").render(tmp_path, environment="production")


def test_bicep_apply_calls_az_deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        captured.append(cmd)
        payload = '{"properties": {"outputs": {"url": {"value": "https://myapp.azurestaticapps.net"}}}}'
        return 0, payload, ""

    monkeypatch.setattr("software_factory.deploy.bicep._run", fake_run)

    bicep_file = tmp_path / "main.bicep"
    bicep_file.write_text(_BICEP_TEMPLATE)
    t = BicepTarget(resource_group="myrg")

    async def no_smoke(result: object) -> bool:
        return True

    monkeypatch.setattr(t, "smoke_test", no_smoke)

    spec = t.render(bicep_file, environment="production")
    result = asyncio.run(t.apply(spec))

    assert result.url == "https://myapp.azurestaticapps.net"
    assert result.spec is spec
    assert any("deployment" in " ".join(c) for c in captured)


def test_bicep_apply_raises_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "ERROR: deployment failed"

    monkeypatch.setattr("software_factory.deploy.bicep._run", fake_run)

    bicep_file = tmp_path / "main.bicep"
    bicep_file.write_text(_BICEP_TEMPLATE)
    t = BicepTarget(resource_group="myrg")
    spec = t.render(bicep_file, environment="production")
    with pytest.raises(DeployError, match="az deployment failed"):
        asyncio.run(t.apply(spec))


# ---------------------------------------------------------------------------
# CrossplaneTarget
# ---------------------------------------------------------------------------

def test_crossplane_provider_name() -> None:
    assert CrossplaneTarget().provider == "crossplane"


def test_crossplane_render_from_file(tmp_path: Path) -> None:
    manifest = tmp_path / "swa.yaml"
    manifest.write_text(_CROSSPLANE_MANIFEST)

    t = CrossplaneTarget(provider_config="azure-prod")
    spec = t.render(manifest, environment="staging")

    assert spec.format == "crossplane"
    assert "StaticWebApp" in spec.content
    assert "azure-prod" in spec.content
    assert spec.parameters["environment"] == "staging"


def test_crossplane_render_from_directory(tmp_path: Path) -> None:
    (tmp_path / "swa.yaml").write_text(_CROSSPLANE_MANIFEST)
    (tmp_path / "keyvault.yaml").write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: kv\n")

    t = CrossplaneTarget()
    spec = t.render(tmp_path, environment="staging")
    assert "---" in spec.content
    assert "StaticWebApp" in spec.content
    assert "ConfigMap" in spec.content


def test_crossplane_render_substitutes_environment(tmp_path: Path) -> None:
    tmpl = "env: {environment}\nprovider: {provider_config}"
    (tmp_path / "res.yaml").write_text(tmpl)

    spec = CrossplaneTarget(provider_config="my-pc").render(tmp_path, environment="staging")
    assert "env: staging" in spec.content
    assert "provider: my-pc" in spec.content


def test_crossplane_render_raises_when_no_manifests(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="no .yaml manifests"):
        CrossplaneTarget().render(tmp_path, environment="production")


def test_crossplane_apply_calls_kubectl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        captured.append(cmd)
        if "jsonpath" in " ".join(cmd):
            return 0, "myapp.azurestaticapps.net\n", ""
        return 0, "", ""

    monkeypatch.setattr("software_factory.deploy.crossplane._run", fake_run)

    manifest = tmp_path / "swa.yaml"
    manifest.write_text(_CROSSPLANE_MANIFEST)
    t = CrossplaneTarget(
        url_resource_ref="staticwebapp.azure.upbound.io/myapp",
        provider_config="azure-prod",
    )

    async def no_smoke(result: object) -> bool:
        return True

    monkeypatch.setattr(t, "smoke_test", no_smoke)

    spec = t.render(manifest, environment="production")
    result = asyncio.run(t.apply(spec))

    assert result.url == "https://myapp.azurestaticapps.net"
    assert any("apply" in c for c in captured)


def test_crossplane_apply_raises_on_kubectl_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "Error: connection refused"

    monkeypatch.setattr("software_factory.deploy.crossplane._run", fake_run)

    manifest = tmp_path / "swa.yaml"
    manifest.write_text(_CROSSPLANE_MANIFEST)
    t = CrossplaneTarget()
    spec = t.render(manifest, environment="production")
    with pytest.raises(DeployError, match="kubectl apply failed"):
        asyncio.run(t.apply(spec))
