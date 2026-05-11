# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Bicep deployment target.

`BicepTarget` applies any Bicep template — SWA, Container App, Key Vault,
database, or any combination. The template content comes from the artifact
path produced by the architect/codegen steps; this class only knows how to
parametrise and submit it.

Usage:
    target = BicepTarget(resource_group="rg-myapp")
    result = await target.deploy(Path("infra/"), environment="staging")
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .base import DeployError, DeployResult, DeployTarget, InfraSpec

_PROVIDER = "azure-bicep"


@dataclass
class BicepTarget(DeployTarget):
    """Apply any Bicep template via ``az deployment group create``.

    Args:
        resource_group: Azure resource group to deploy into.
        subscription_id: Azure subscription. Defaults to
            ``$AZURE_SUBSCRIPTION_ID``.
        parameters: Extra Bicep parameter overrides (name=value pairs) merged
            with whatever ``render()`` derives from the artifact.
        location: Fallback location written into parameters if the template
            needs it and none is provided.
    """

    resource_group: str
    subscription_id: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    location: str = "spaincentral"

    def __post_init__(self) -> None:
        if not self.subscription_id:
            self.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

    @property
    def provider(self) -> str:
        return _PROVIDER

    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        """Read the Bicep template from ``artifact_path`` and parametrise it.

        ``artifact_path`` may be:
        - a ``.bicep`` file — used directly.
        - a directory — ``main.bicep`` inside it is used.

        Parameters merged (in order, later wins):
        1. ``location`` and ``environment`` defaults.
        2. Extra ``self.parameters`` set on the target.
        """
        bicep_file = _resolve_bicep(artifact_path)
        content = bicep_file.read_text(encoding="utf-8")

        params = {"location": self.location, "environment": environment, **self.parameters}

        return InfraSpec(
            format="bicep",
            content=content,
            parameters=params,
            source_template=str(bicep_file),
        )

    async def apply(self, spec: InfraSpec) -> DeployResult:
        """Submit the Bicep spec and return the deployment result.

        The URL is read from the ``url`` output of the Bicep template.
        Templates that expose a different output key should subclass and
        override ``_extract_url()``.
        """
        with tempfile.NamedTemporaryFile(suffix=".bicep", mode="w", delete=False, encoding="utf-8") as f:
            f.write(spec.content)
            bicep_file = f.name

        params_args = [f"{k}={v}" for k, v in spec.parameters.items()]
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

    def _extract_url(self, outputs: dict) -> str:
        """Extract the deployment URL from az deployment outputs.

        Looks for an output named ``url`` by convention. Override this method
        if the Bicep template uses a different output key.
        """
        return outputs.get("url", {}).get("value", "")


def _resolve_bicep(artifact_path: Path) -> Path:
    if artifact_path.is_file() and artifact_path.suffix == ".bicep":
        return artifact_path
    if artifact_path.is_dir():
        main = artifact_path / "main.bicep"
        if main.is_file():
            return main
        bicep_files = list(artifact_path.glob("*.bicep"))
        if len(bicep_files) == 1:
            return bicep_files[0]
        if bicep_files:
            raise DeployError(_PROVIDER, f"multiple .bicep files in {artifact_path} — add a main.bicep")
    raise DeployError(_PROVIDER, f"no .bicep template found at {artifact_path}")


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_out, raw_err = await proc.communicate()
    return proc.returncode or 0, raw_out.decode(), raw_err.decode()
