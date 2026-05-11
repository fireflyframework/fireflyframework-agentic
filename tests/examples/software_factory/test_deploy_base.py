# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the DeployTarget abstraction."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from software_factory.deploy.base import DeployError, DeployResult, DeployTarget


class _OKTarget(DeployTarget):
    @property
    def provider(self) -> str:
        return "test-ok"

    async def deploy(self, artifact_path: Path, *, environment: str = "production") -> DeployResult:
        return DeployResult(
            url="https://example.com",
            environment=environment,
            provider=self.provider,
            artifact_ref=str(artifact_path),
            smoke_passed=True,
        )


class _FailTarget(DeployTarget):
    @property
    def provider(self) -> str:
        return "test-fail"

    async def deploy(self, artifact_path: Path, *, environment: str = "production") -> DeployResult:
        raise DeployError(self.provider, "deploy failed", exit_code=1)


def test_deploy_result_defaults() -> None:
    r = DeployResult(url="https://x.com", environment="prod", provider="p", artifact_ref="/a")
    assert r.smoke_passed is False
    assert r.metadata == {}


def test_ok_target_returns_result(tmp_path: Path) -> None:
    target = _OKTarget()
    result = asyncio.run(target.deploy(tmp_path))
    assert result.url == "https://example.com"
    assert result.smoke_passed is True
    assert result.provider == "test-ok"


def test_fail_target_raises_deploy_error(tmp_path: Path) -> None:
    target = _FailTarget()
    with pytest.raises(DeployError) as exc_info:
        asyncio.run(target.deploy(tmp_path))
    assert "deploy failed" in str(exc_info.value)
    assert exc_info.value.exit_code == 1


def test_deploy_error_includes_provider() -> None:
    err = DeployError("my-provider", "something went wrong")
    assert "my-provider" in str(err)
    assert "something went wrong" in str(err)
