# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Crossplane deployment target.

`CrossplaneTarget` applies any set of Crossplane Composite Resource (XR)
manifests — SWA, databases, key vaults, networking, or any combination.
The manifest content comes from the artifact path produced by the
architect/codegen steps; this class only knows how to submit and wait.

Crossplane is cloud-agnostic: the same ``kubectl apply`` + wait workflow
works for Azure (provider-azure), AWS (provider-aws), GCP (provider-gcp),
and any other Upbound provider. The manifests themselves encode the cloud.

Usage:
    target = CrossplaneTarget(
        url_resource_ref="staticwebapp.azure.upbound.io/myapp",
        url_jsonpath="{.status.atProvider.defaultHostname}",
    )
    result = await target.deploy(Path("infra/"), environment="staging")
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .base import DeployError, DeployResult, DeployTarget, InfraSpec

_PROVIDER = "crossplane"


@dataclass
class CrossplaneTarget(DeployTarget):
    """Apply any Crossplane XR manifests via ``kubectl apply``.

    Args:
        url_resource_ref: The ``kubectl`` resource reference for the primary
            workload, e.g. ``staticwebapp.azure.upbound.io/myapp``. Used for
            ``kubectl wait --for=condition=Ready`` and URL extraction.
        url_jsonpath: JSONPath expression to extract the live URL from the
            primary resource status, e.g.
            ``{.status.atProvider.defaultHostname}``.
        kubectl_context: Optional kubeconfig context name.
        provider_config: Crossplane ProviderConfig name injected into
            manifests that reference ``{provider_config}``.
        wait_timeout: Seconds to wait for resources to become Ready.
    """

    url_resource_ref: str = ""
    url_jsonpath: str = "{.status.atProvider.defaultHostname}"
    kubectl_context: str = ""
    provider_config: str = "default"
    wait_timeout: int = 300

    @property
    def provider(self) -> str:
        return _PROVIDER

    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        """Read Crossplane manifests from ``artifact_path`` and return an InfraSpec.

        ``artifact_path`` may be:
        - a single ``.yaml`` / ``.yml`` file — used directly.
        - a directory — all ``.yaml`` / ``.yml`` files are concatenated with
          ``---`` separators into a single manifest bundle.

        Template variables ``{environment}`` and ``{provider_config}`` are
        substituted in the manifest content.
        """
        content = _read_manifests(artifact_path)
        content = content.replace("{environment}", environment).replace(
            "{provider_config}", self.provider_config
        )
        return InfraSpec(
            format="crossplane",
            content=content,
            parameters={"environment": environment, "provider_config": self.provider_config},
            source_template=str(artifact_path),
        )

    async def apply(self, spec: InfraSpec) -> DeployResult:
        """Apply the manifests, wait for Ready, then extract the URL."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(spec.content)
            manifest_file = f.name

        base = self._base_cmd()

        exit_code, _, stderr = await _run(base + ["apply", "-f", manifest_file])
        Path(manifest_file).unlink(missing_ok=True)
        if exit_code != 0:
            raise DeployError(_PROVIDER, f"kubectl apply failed (exit {exit_code}):\n{stderr}", exit_code=exit_code)

        url = ""
        if self.url_resource_ref:
            await self._wait_ready(base)
            url = await self._read_url(base)

        return DeployResult(
            url=url,
            environment=spec.parameters.get("environment", "production"),
            provider=self.provider,
            spec=spec,
            metadata={"resource_ref": self.url_resource_ref},
        )

    def _base_cmd(self) -> list[str]:
        cmd = ["kubectl"]
        if self.kubectl_context:
            cmd += ["--context", self.kubectl_context]
        return cmd

    async def _wait_ready(self, base: list[str]) -> None:
        cmd = base + [
            "wait", self.url_resource_ref,
            "--for=condition=Ready",
            f"--timeout={self.wait_timeout}s",
        ]
        exit_code, _, stderr = await _run(cmd)
        if exit_code != 0:
            raise DeployError(_PROVIDER, f"resource did not become Ready:\n{stderr}", exit_code=exit_code)

    async def _read_url(self, base: list[str]) -> str:
        cmd = base + ["get", self.url_resource_ref, "-o", f"jsonpath={self.url_jsonpath}"]
        exit_code, stdout, _ = await _run(cmd)
        hostname = stdout.strip()
        if exit_code == 0 and hostname:
            return f"https://{hostname}" if not hostname.startswith("http") else hostname
        return ""


def _read_manifests(artifact_path: Path) -> str:
    if artifact_path.is_file() and artifact_path.suffix in {".yaml", ".yml"}:
        return artifact_path.read_text(encoding="utf-8")
    if artifact_path.is_dir():
        files = sorted(artifact_path.glob("*.yaml")) + sorted(artifact_path.glob("*.yml"))
        if not files:
            raise DeployError(_PROVIDER, f"no .yaml manifests found in {artifact_path}")
        return "\n---\n".join(f.read_text(encoding="utf-8") for f in files)
    raise DeployError(_PROVIDER, f"no Crossplane manifests found at {artifact_path}")


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_out, raw_err = await proc.communicate()
    return proc.returncode or 0, raw_out.decode(), raw_err.decode()
