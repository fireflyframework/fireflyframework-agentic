# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Abstract deployment target interface.

Every cloud provider / runtime (Azure SWA, Container Apps, AKS, AWS Amplify,
GCP Cloud Run, …) implements `DeployTarget`. The deployer agent and all tests
work exclusively against this interface — concrete providers are never imported
by agent code directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DeployResult:
    """Outcome of a single deployment operation."""

    url: str
    environment: str
    provider: str
    artifact_ref: str
    metadata: dict[str, str] = field(default_factory=dict)
    smoke_passed: bool = False


class DeployTarget(ABC):
    """Abstract interface that every deployment provider must implement.

    A target encapsulates provider-specific credentials and configuration.
    Agents receive a pre-configured target via dependency injection.
    """

    @property
    @abstractmethod
    def provider(self) -> str:
        """Short identifier for the provider, e.g. 'azure-swa'."""

    @abstractmethod
    async def deploy(self, artifact_path: Path, *, environment: str = "production") -> DeployResult:
        """Deploy the artifact at `artifact_path` to the named environment.

        Args:
            artifact_path: Directory or file produced by the builder step.
            environment: Target environment name (e.g. 'staging', 'production').

        Returns:
            `DeployResult` with the live URL and smoke-test outcome.

        Raises:
            DeployError: If the provider reports a deployment failure.
        """

    async def smoke_test(self, result: DeployResult) -> bool:
        """Verify the deployment is reachable. Default: HTTP GET on `result.url`."""
        import urllib.request

        try:
            with urllib.request.urlopen(result.url, timeout=10) as resp:  # noqa: S310
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False


class DeployError(Exception):
    """Raised when a deployment provider reports a failure."""

    def __init__(self, provider: str, message: str, *, exit_code: int = 1) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.exit_code = exit_code
