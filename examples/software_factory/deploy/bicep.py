# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Bicep-based deployment targets.

`render()` generates a Bicep template for the requested resource type.
`apply()` submits it via `az deployment group create` and reads the outputs.

Adding a new Azure resource type = adding a new Bicep template constant and
a subclass that sets `_TEMPLATE` and extracts the right output key.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .base import DeployError, DeployResult, DeployTarget, InfraSpec

_PROVIDER = "azure-bicep"

# ---------------------------------------------------------------------------
# Bicep templates
# ---------------------------------------------------------------------------

_SWA_BICEP = """\
@description('Name of the Static Web App resource.')
param appName string

@description('Azure region.')
param location string = resourceGroup().location

@description('SWA SKU (Free or Standard).')
param sku string = 'Free'

resource swa 'Microsoft.Web/staticSites@2022-09-01' = {
  name: appName
  location: location
  sku: {
    name: sku
    tier: sku
  }
  properties: {}
}

output url string = 'https://${swa.properties.defaultHostname}'
output deploymentToken string = swa.listSecrets().properties.apiKey
"""


# ---------------------------------------------------------------------------
# Base Bicep target
# ---------------------------------------------------------------------------

@dataclass
class BicepTarget(DeployTarget):
    """Generic Bicep deployment target.

    Subclasses supply `_TEMPLATE` (the Bicep content) and override
    `_parameters()` to return the `az deployment` parameter values.
    Subclasses may also override `_extract_url()` if the output key differs.
    """

    resource_group: str
    subscription_id: str = ""

    def __post_init__(self) -> None:
        if not self.subscription_id:
            self.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

    @property
    def provider(self) -> str:
        return _PROVIDER

    # -- subclass API -------------------------------------------------------

    _TEMPLATE: ClassVar[str] = ""

    def _parameters(self, artifact_path: Path, environment: str) -> dict[str, str]:
        """Return Bicep parameter values for this deployment."""
        return {}

    def _extract_url(self, az_outputs: dict) -> str:
        """Extract the deployment URL from `az deployment` outputs dict."""
        return az_outputs.get("url", {}).get("value", "")

    # -- DeployTarget -------------------------------------------------------

    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        return InfraSpec(
            format="bicep",
            content=self._TEMPLATE,
            parameters=self._parameters(artifact_path, environment),
            source_template=type(self).__name__,
        )

    async def apply(self, spec: InfraSpec) -> DeployResult:
        with tempfile.NamedTemporaryFile(suffix=".bicep", mode="w", delete=False) as f:
            f.write(spec.content)
            bicep_file = f.name

        params_args = []
        for k, v in spec.parameters.items():
            params_args += [f"{k}={v}"]

        cmd = [
            "az", "deployment", "group", "create",
            "--resource-group", self.resource_group,
            "--template-file", bicep_file,
            "--output", "json",
        ]
        if params_args:
            cmd += ["--parameters", *params_args]
        if self.subscription_id:
            cmd += ["--subscription", self.subscription_id]

        exit_code, stdout, stderr = await _run(cmd)
        Path(bicep_file).unlink(missing_ok=True)

        if exit_code != 0:
            raise DeployError(_PROVIDER, f"az deployment failed (exit {exit_code}):\n{stderr}", exit_code=exit_code)

        try:
            outputs = json.loads(stdout).get("properties", {}).get("outputs", {})
        except json.JSONDecodeError as exc:
            raise DeployError(_PROVIDER, f"could not parse az deployment output: {exc}") from exc

        url = self._extract_url(outputs)
        return DeployResult(
            url=url,
            environment=spec.parameters.get("environment", "production"),
            provider=self.provider,
            spec=spec,
            metadata={"resource_group": self.resource_group},
        )


# ---------------------------------------------------------------------------
# Azure Static Web Apps
# ---------------------------------------------------------------------------

@dataclass
class BicepSWATarget(BicepTarget):
    """Deploy an Azure Static Web App via Bicep.

    Renders a Bicep template that provisions (or updates) the SWA resource,
    then uploads static content using the deployment token from the Bicep
    output. The static files are expected in `artifact_path`.
    """

    app_name: str = ""
    location: str = "spaincentral"

    _TEMPLATE: ClassVar[str] = _SWA_BICEP

    def _parameters(self, artifact_path: Path, environment: str) -> dict[str, str]:
        return {
            "appName": self.app_name,
            "location": self.location,
            "environment": environment,
        }

    async def apply(self, spec: InfraSpec) -> DeployResult:
        result = await super().apply(spec)

        # Upload static content using the deployment token from Bicep output.
        # The token is written to $GITHUB_OUTPUT by the Bicep step; here we
        # read it from the spec parameters if pre-provisioned, or from env.
        token = spec.parameters.get("deploymentToken") or os.environ.get("AZURE_STATIC_WEB_APPS_API_TOKEN", "")
        if token and spec.parameters.get("artifact_path"):
            await self._upload_content(Path(spec.parameters["artifact_path"]), token, result.environment)

        return result

    async def _upload_content(self, artifact_path: Path, token: str, environment: str) -> None:
        cmd = [
            "az", "staticwebapp", "deploy",
            "--name", self.app_name,
            "--resource-group", self.resource_group,
            "--source", str(artifact_path),
            "--deployment-token", token,
            "--environment-name", environment,
            "--no-wait",
        ]
        exit_code, _, stderr = await _run(cmd)
        if exit_code != 0:
            raise DeployError(self.provider, f"static content upload failed:\n{stderr}", exit_code=exit_code)


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_out, raw_err = await proc.communicate()
    return proc.returncode or 0, raw_out.decode(), raw_err.decode()
