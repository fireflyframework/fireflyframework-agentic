# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Declarative deployment targets for the software factory.

The deployer agent generates an `InfraSpec` from templates produced by the
architect/codegen steps, then submits it to the target platform. No agent
code calls cloud CLIs directly.

Targets:
- `BicepTarget`      — applies any Bicep template via ``az deployment group create``
- `CrossplaneTarget` — applies any Crossplane XR manifests via ``kubectl apply``
"""

from .base import DeployError, DeployResult, DeployTarget, InfraSpec
from .bicep import BicepTarget
from .crossplane import CrossplaneTarget

__all__ = [
    "DeployError",
    "DeployResult",
    "DeployTarget",
    "InfraSpec",
    "BicepTarget",
    "CrossplaneTarget",
]
