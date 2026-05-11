# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the Azure SWA deployment target."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from software_factory.deploy.base import DeployError
from software_factory.deploy.swa import AzureSWATarget


def test_provider_name() -> None:
    target = AzureSWATarget(app_name="my-app", resource_group="my-rg", deployment_token="tok")
    assert target.provider == "azure-swa"


def test_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_STATIC_WEB_APPS_API_TOKEN", "env-token")
    target = AzureSWATarget(app_name="app", resource_group="rg")
    assert target.deployment_token == "env-token"


def test_raises_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_STATIC_WEB_APPS_API_TOKEN", raising=False)
    target = AzureSWATarget(app_name="app", resource_group="rg")
    with pytest.raises(DeployError, match="API_TOKEN"):
        asyncio.run(target.deploy(tmp_path))


def test_raises_when_artifact_missing() -> None:
    target = AzureSWATarget(app_name="app", resource_group="rg", deployment_token="tok")
    with pytest.raises(DeployError, match="does not exist"):
        asyncio.run(target.deploy(Path("/nonexistent/path")))


def test_deploy_uses_swa_cli_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When `swa` is on PATH, the command uses the swa CLI."""
    captured: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        captured.append(cmd)
        return 0, "Deployed to https://happy-tree.azurestaticapps.net", ""

    monkeypatch.setattr("software_factory.deploy.swa._run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/swa")

    target = AzureSWATarget(app_name="app", resource_group="rg", deployment_token="tok")

    async def no_smoke(result: object) -> bool:
        return True

    monkeypatch.setattr(target, "smoke_test", no_smoke)

    result = asyncio.run(target.deploy(tmp_path))
    assert result.url == "https://happy-tree.azurestaticapps.net"
    assert captured[0][0] == "swa"


def test_deploy_falls_back_to_az_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When `swa` is not on PATH, falls back to `az staticwebapp`."""
    captured: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        captured.append(cmd)
        if cmd[0] == "az" and "deploy" in cmd:
            return 0, "", ""
        if cmd[0] == "az" and "show" in cmd:
            return 0, "happy-tree.azurestaticapps.net\n", ""
        return 0, "", ""

    monkeypatch.setattr("software_factory.deploy.swa._run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _: None)

    target = AzureSWATarget(app_name="app", resource_group="rg", deployment_token="tok")

    async def no_smoke(result: object) -> bool:
        return True

    monkeypatch.setattr(target, "smoke_test", no_smoke)

    result = asyncio.run(target.deploy(tmp_path))
    assert result.url == "https://happy-tree.azurestaticapps.net"
    assert any(c[0] == "az" for c in captured)


def test_deploy_raises_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "fatal: deploy failed"

    monkeypatch.setattr("software_factory.deploy.swa._run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/swa")

    target = AzureSWATarget(app_name="app", resource_group="rg", deployment_token="tok")
    with pytest.raises(DeployError, match="swa deploy failed"):
        asyncio.run(target.deploy(tmp_path))


def test_extract_url_parses_swa_domain() -> None:
    target = AzureSWATarget(app_name="app", resource_group="rg", deployment_token="tok")
    line = "Deployment complete: https://proud-ocean.azurestaticapps.net"
    assert target._extract_url(line) == "https://proud-ocean.azurestaticapps.net"


def test_extract_url_returns_empty_when_no_match() -> None:
    target = AzureSWATarget(app_name="app", resource_group="rg", deployment_token="tok")
    assert target._extract_url("no url here") == ""
