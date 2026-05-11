# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Crossplane-based deployment targets.

`render()` generates a Crossplane Composite Resource (XR) manifest.
`apply()` submits it via `kubectl apply` and waits for the `Ready` condition.

Crossplane works across clouds: Azure, AWS, and GCP all have Crossplane
providers that accept the same `kubectl apply` workflow. Adding a new cloud
= adding a new XR template and subclass; the apply logic is unchanged.

Requires a Kubernetes cluster with Crossplane installed and a configured
provider (e.g. `provider-azure-web` for Azure Static Web Apps).
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .base import DeployError, DeployResult, DeployTarget, InfraSpec

_PROVIDER = "crossplane"

# ---------------------------------------------------------------------------
# XR templates
# ---------------------------------------------------------------------------

_SWA_XR = """\
apiVersion: azure.upbound.io/v1beta1
kind: StaticWebApp
metadata:
  name: {app_name}
  annotations:
    crossplane.io/external-name: {app_name}
spec:
  forProvider:
    location: {location}
    resourceGroupName: {resource_group}
    skuSize: Free
    skuTier: Free
    tags:
      environment: {environment}
      managed-by: firefly-factory
  providerConfigRef:
    name: {provider_config}
  writeConnectionSecretToRef:
    name: {app_name}-connection
    namespace: crossplane-system
"""


# ---------------------------------------------------------------------------
# Base Crossplane target
# ---------------------------------------------------------------------------

@dataclass
class CrossplaneTarget(DeployTarget):
    """Generic Crossplane deployment target.

    Subclasses supply `_XR_TEMPLATE` and implement `_template_vars()`.
    The `apply()` method is shared: `kubectl apply` + wait for Ready.
    """

    provider_config: str = "azure-provider"
    kubectl_context: str = ""

    @property
    def provider(self) -> str:
        return _PROVIDER

    _XR_TEMPLATE: ClassVar[str] = ""

    def _template_vars(self, artifact_path: Path, environment: str) -> dict[str, str]:
        return {}

    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        vars_ = self._template_vars(artifact_path, environment)
        content = self._XR_TEMPLATE.format(**vars_)
        return InfraSpec(
            format="crossplane",
            content=content,
            parameters=vars_,
            source_template=type(self).__name__,
        )

    async def apply(self, spec: InfraSpec) -> DeployResult:
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(spec.content)
            manifest_file = f.name

        base_cmd = ["kubectl"]
        if self.kubectl_context:
            base_cmd += ["--context", self.kubectl_context]

        apply_cmd = base_cmd + ["apply", "-f", manifest_file]
        exit_code, _, stderr = await _run(apply_cmd)
        Path(manifest_file).unlink(missing_ok=True)

        if exit_code != 0:
            raise DeployError(_PROVIDER, f"kubectl apply failed (exit {exit_code}):\n{stderr}", exit_code=exit_code)

        resource_ref = self._resource_ref(spec)
        url = await self._wait_for_ready(base_cmd, resource_ref, spec)

        return DeployResult(
            url=url,
            environment=spec.parameters.get("environment", "production"),
            provider=self.provider,
            spec=spec,
            metadata={"resource_ref": resource_ref},
        )

    def _resource_ref(self, spec: InfraSpec) -> str:
        """Return the kubectl resource reference for wait/get commands."""
        return ""

    async def _wait_for_ready(self, base_cmd: list[str], resource_ref: str, spec: InfraSpec) -> str:
        """Wait for the Crossplane resource to reach Ready=True and return its URL."""
        if not resource_ref:
            return ""

        wait_cmd = base_cmd + [
            "wait", resource_ref,
            "--for=condition=Ready",
            "--timeout=300s",
        ]
        exit_code, _, stderr = await _run(wait_cmd)
        if exit_code != 0:
            raise DeployError(_PROVIDER, f"resource did not become ready:\n{stderr}", exit_code=exit_code)

        return await self._get_url(base_cmd, resource_ref, spec)

    async def _get_url(self, base_cmd: list[str], resource_ref: str, spec: InfraSpec) -> str:
        """Read the deployment URL from the resource status."""
        return ""


# ---------------------------------------------------------------------------
# Azure Static Web Apps via Crossplane
# ---------------------------------------------------------------------------

@dataclass
class CrossplaneSWATarget(CrossplaneTarget):
    """Deploy an Azure Static Web App using the Crossplane Azure provider.

    Renders a `StaticWebApp` XR manifest, applies it, and waits for the
    resource to reconcile. The live URL is read from the resource status.

    Requires `provider-azure-web` installed in the cluster.
    """

    app_name: str = ""
    resource_group: str = ""
    location: str = "spaincentral"

    _XR_TEMPLATE: ClassVar[str] = _SWA_XR

    def _template_vars(self, artifact_path: Path, environment: str) -> dict[str, str]:
        return {
            "app_name": self.app_name,
            "resource_group": self.resource_group,
            "location": self.location,
            "environment": environment,
            "provider_config": self.provider_config,
        }

    def _resource_ref(self, spec: InfraSpec) -> str:
        return f"staticwebapp.azure.upbound.io/{self.app_name}"

    async def _get_url(self, base_cmd: list[str], resource_ref: str, spec: InfraSpec) -> str:
        cmd = base_cmd + [
            "get", resource_ref,
            "-o", "jsonpath={.status.atProvider.defaultHostname}",
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
