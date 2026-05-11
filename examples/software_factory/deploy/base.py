# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Deployment abstraction built around declarative infrastructure specs.

The deployer agent never calls cloud CLIs directly. Instead it:
  1. Calls `render()` to produce an `InfraSpec` (Bicep, Crossplane XR, …).
  2. Calls `apply()` to submit that spec to the target platform.
  3. Waits for the platform to reconcile and returns a `DeployResult`.

Adding a new cloud or runtime = implementing `render()` and `apply()` for
that platform's spec format. Agent code never changes.
"""

from __future__ import annotations

import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class InfraSpec:
    """Declarative infrastructure specification produced by the deployer.

    This is the primary output artifact of a deploy step — it is saved to
    the factory artifact store so every deployment is fully auditable.
    """

    format: Literal["bicep", "crossplane"]
    content: str
    parameters: dict[str, str] = field(default_factory=dict)
    source_template: str = ""


@dataclass(frozen=True)
class DeployResult:
    """Outcome of a single deployment operation."""

    url: str
    environment: str
    provider: str
    spec: InfraSpec
    smoke_passed: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class DeployTarget(ABC):
    """Abstract spec-driven deployment target.

    Subclasses implement two methods:
    - `render()` — produce the `InfraSpec` for the given artifact.
    - `apply()` — submit the spec and wait for the platform to reconcile.

    The concrete `deploy()` method chains them and adds the smoke test.
    """

    @property
    @abstractmethod
    def provider(self) -> str:
        """Short identifier, e.g. 'azure-bicep-swa', 'crossplane-azure-swa'."""

    @abstractmethod
    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        """Generate the infrastructure spec for the artifact.

        The spec must be self-contained: applying it to the platform should
        produce a running deployment with no additional inputs.
        """

    @abstractmethod
    async def apply(self, spec: InfraSpec) -> DeployResult:
        """Submit the spec to the platform and wait for reconciliation.

        Returns a `DeployResult` with `smoke_passed=False`; the base
        `deploy()` method runs the smoke test and updates the flag.

        Raises:
            DeployError: If the platform rejects or fails the deployment.
        """

    async def deploy(self, artifact_path: Path, *, environment: str = "production") -> DeployResult:
        """Render the spec, apply it, smoke-test, and return the result."""
        spec = self.render(artifact_path, environment=environment)
        result = await self.apply(spec)
        smoke_ok = await self.smoke_test(result)
        return DeployResult(
            url=result.url,
            environment=result.environment,
            provider=result.provider,
            spec=result.spec,
            smoke_passed=smoke_ok,
            metadata=result.metadata,
        )

    async def smoke_test(self, result: DeployResult) -> bool:
        """HTTP GET on `result.url`; returns True on HTTP 200."""
        try:
            with urllib.request.urlopen(result.url, timeout=10) as resp:  # noqa: S310
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False


class DeployError(Exception):
    """Raised when the platform rejects or fails a deployment."""

    def __init__(self, provider: str, message: str, *, exit_code: int = 1) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.exit_code = exit_code
