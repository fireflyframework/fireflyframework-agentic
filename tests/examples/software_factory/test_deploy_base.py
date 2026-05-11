# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the InfraSpec / DeployTarget abstraction."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from software_factory.deploy.base import DeployError, DeployResult, DeployTarget, InfraSpec


class _OKTarget(DeployTarget):
    @property
    def provider(self) -> str:
        return "test-ok"

    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        return InfraSpec(format="bicep", content="param x string", parameters={"x": "1"})

    async def apply(self, spec: InfraSpec) -> DeployResult:
        return DeployResult(
            url="https://example.com",
            environment="production",
            provider=self.provider,
            spec=spec,
            smoke_passed=False,
        )

    async def smoke_test(self, result: DeployResult) -> bool:
        return True


class _FailTarget(DeployTarget):
    @property
    def provider(self) -> str:
        return "test-fail"

    def render(self, artifact_path: Path, *, environment: str) -> InfraSpec:
        return InfraSpec(format="crossplane", content="apiVersion: v1", parameters={})

    async def apply(self, spec: InfraSpec) -> DeployResult:
        raise DeployError(self.provider, "apply failed", exit_code=1)


def test_infra_spec_defaults() -> None:
    spec = InfraSpec(format="bicep", content="param x string")
    assert spec.parameters == {}
    assert spec.source_template == ""


def test_deploy_result_carries_spec() -> None:
    spec = InfraSpec(format="bicep", content="x")
    result = DeployResult(url="https://x.com", environment="prod", provider="p", spec=spec)
    assert result.spec is spec
    assert result.smoke_passed is False


def test_ok_target_deploy_chains_render_apply_smoke(tmp_path: Path) -> None:
    target = _OKTarget()
    result = asyncio.run(target.deploy(tmp_path))
    assert result.url == "https://example.com"
    assert result.smoke_passed is True
    assert result.spec.format == "bicep"


def test_fail_target_raises_deploy_error(tmp_path: Path) -> None:
    target = _FailTarget()
    with pytest.raises(DeployError) as exc_info:
        asyncio.run(target.deploy(tmp_path))
    assert "apply failed" in str(exc_info.value)
    assert exc_info.value.exit_code == 1


def test_deploy_error_includes_provider() -> None:
    err = DeployError("my-provider", "something went wrong")
    assert "my-provider" in str(err)
    assert err.exit_code == 1
