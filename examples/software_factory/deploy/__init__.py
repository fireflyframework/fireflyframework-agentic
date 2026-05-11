# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Deployment target abstraction for the software factory.

Concrete targets (SWA, Container Apps, K8s, …) implement `DeployTarget`.
The deployer agent works exclusively against this interface.
"""

from .base import DeployResult, DeployTarget

__all__ = ["DeployResult", "DeployTarget"]
