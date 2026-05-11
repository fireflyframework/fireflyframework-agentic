# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Deployer agent — takes a built artifact and deploys it to a target environment.

The agent is target-agnostic: it receives a pre-configured `DeployTarget`
and orchestrates deploy → smoke → report. All provider-specific logic lives
in the `deploy/` module.

Usage (from the action runtime):
    target = AzureSWATarget(app_name=..., resource_group=...)
    result = await deploy(artifact_path=Path("dist/"), target=target)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..deploy.base import DeployError, DeployResult, DeployTarget
from ..exceptions import ActionRuntimeError
from ..rubrics import load_rubric

logger = logging.getLogger(__name__)

RUBRIC = load_rubric("deployer")


async def deploy(artifact_path: Path, target: DeployTarget, *, environment: str = "production") -> DeployResult:
    """Deploy `artifact_path` using `target` and return the result.

    Raises:
        ActionRuntimeError: If the deployment fails after all retries.
    """
    logger.info("deployer: deploying %s via %s to %s", artifact_path, target.provider, environment)

    try:
        result = await target.deploy(artifact_path, environment=environment)
    except DeployError as exc:
        raise ActionRuntimeError(str(exc)) from exc

    _log_result(result)
    _check_rubric(result)
    return result


def _log_result(result: DeployResult) -> None:
    logger.info(
        "deployer: deployed to %s (smoke=%s provider=%s)",
        result.url,
        result.smoke_passed,
        result.provider,
    )


def _check_rubric(result: DeployResult) -> None:
    """Raise if the result fails the deployer rubric's hard criteria."""
    if not result.url:
        raise ActionRuntimeError("deployer rubric: no deployment URL returned")
    if not result.smoke_passed:
        raise ActionRuntimeError(
            f"deployer rubric: smoke test failed — {result.url} did not return HTTP 200"
        )


def result_to_artifact(result: DeployResult) -> str:
    """Serialize a DeployResult to JSON for upload as a factory artifact."""
    return json.dumps(
        {
            "url": result.url,
            "environment": result.environment,
            "provider": result.provider,
            "artifact_ref": result.artifact_ref,
            "smoke_passed": result.smoke_passed,
            "metadata": result.metadata,
        },
        indent=2,
    )
