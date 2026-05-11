# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Declarative deployment targets for the software factory.

The deployer agent generates an `InfraSpec` (Bicep or Crossplane XR) and
submits it to the platform. No agent code calls cloud CLIs directly.

Targets:
- `BicepSWATarget` — Azure Static Web Apps via Bicep + az deployment
- `CrossplaneSWATarget` — Azure Static Web Apps via Crossplane XR + kubectl
"""

from .base import DeployError, DeployResult, DeployTarget, InfraSpec
from .bicep import BicepSWATarget, BicepTarget
from .crossplane import CrossplaneSWATarget, CrossplaneTarget

__all__ = [
    "DeployError",
    "DeployResult",
    "DeployTarget",
    "InfraSpec",
    "BicepTarget",
    "BicepSWATarget",
    "CrossplaneTarget",
    "CrossplaneSWATarget",
]
