# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Azure Static Web Apps deployment target.

Uses the `swa` CLI (https://azure.github.io/static-web-apps-cli/) when
available, falling back to `az staticwebapp` commands. Both require the
SWA deployment token to be set in `AZURE_STATIC_WEB_APPS_API_TOKEN` (or
passed explicitly).

The implementation is intentionally thin: it shells out to the same CLI
tools used in human-operated deployments, which means it benefits from
all future SWA CLI improvements without code changes here.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .base import DeployError, DeployResult, DeployTarget

_PROVIDER = "azure-swa"


@dataclass
class AzureSWATarget(DeployTarget):
    """Deployment target for Azure Static Web Apps.

    Args:
        app_name: The SWA resource name in Azure.
        resource_group: Azure resource group containing the SWA.
        deployment_token: SWA deployment token. Defaults to
            ``$AZURE_STATIC_WEB_APPS_API_TOKEN``.
        subscription_id: Azure subscription ID. Defaults to
            ``$AZURE_SUBSCRIPTION_ID``.
    """

    app_name: str
    resource_group: str
    deployment_token: str = ""
    subscription_id: str = ""

    def __post_init__(self) -> None:
        if not self.deployment_token:
            self.deployment_token = os.environ.get("AZURE_STATIC_WEB_APPS_API_TOKEN", "")
        if not self.subscription_id:
            self.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

    @property
    def provider(self) -> str:
        return _PROVIDER

    async def deploy(self, artifact_path: Path, *, environment: str = "production") -> DeployResult:
        """Deploy `artifact_path` to the SWA using the `swa` CLI."""
        if not artifact_path.exists():
            raise DeployError(_PROVIDER, f"artifact path does not exist: {artifact_path}")
        if not self.deployment_token:
            raise DeployError(_PROVIDER, "AZURE_STATIC_WEB_APPS_API_TOKEN is not set")

        cmd = self._build_command(artifact_path, environment)
        exit_code, stdout, stderr = await _run(cmd)

        if exit_code != 0:
            raise DeployError(
                _PROVIDER,
                f"swa deploy failed (exit {exit_code}):\n{stderr}",
                exit_code=exit_code,
            )

        url = self._extract_url(stdout) or await self._fetch_url_from_az()
        result = DeployResult(
            url=url,
            environment=environment,
            provider=_PROVIDER,
            artifact_ref=str(artifact_path),
            metadata={"app_name": self.app_name, "resource_group": self.resource_group},
        )
        smoke_ok = await self.smoke_test(result)
        return DeployResult(**{**result.__dict__, "smoke_passed": smoke_ok})

    def _build_command(self, artifact_path: Path, environment: str) -> list[str]:
        if shutil.which("swa"):
            cmd = [
                "swa", "deploy",
                str(artifact_path),
                "--deployment-token", self.deployment_token,
                "--env", environment,
            ]
        else:
            cmd = [
                "az", "staticwebapp", "deploy",
                "--name", self.app_name,
                "--resource-group", self.resource_group,
                "--source", str(artifact_path),
                "--deployment-token", self.deployment_token,
                "--environment-name", environment,
            ]
        return cmd

    def _extract_url(self, stdout: str) -> str:
        """Parse the deployment URL from swa CLI output."""
        for line in stdout.splitlines():
            if "https://" in line and ".azurestaticapps.net" in line:
                parts = line.split()
                for part in parts:
                    if part.startswith("https://"):
                        return part.rstrip(".,")
        return ""

    async def _fetch_url_from_az(self) -> str:
        """Fallback: ask the Azure API for the SWA default hostname."""
        cmd = [
            "az", "staticwebapp", "show",
            "--name", self.app_name,
            "--resource-group", self.resource_group,
            "--query", "defaultHostname",
            "--output", "tsv",
        ]
        exit_code, stdout, _ = await _run(cmd)
        hostname = stdout.strip()
        if exit_code == 0 and hostname:
            return f"https://{hostname}"
        return ""


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_out, raw_err = await proc.communicate()
    return proc.returncode or 0, raw_out.decode(), raw_err.decode()
