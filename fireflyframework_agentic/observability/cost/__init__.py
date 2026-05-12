# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Cost-resolution subpackage."""

from fireflyframework_agentic.observability.cost.resolvers import (
    DEFAULT_RESOLVERS,
    CostContext,
    CostFn,
    genai_prices_cost,
    provider_reported_cost,
    resolve_cost,
)
from fireflyframework_agentic.observability.cost.tiers import CallTier

__all__ = [
    "CallTier",
    "CostContext",
    "CostFn",
    "DEFAULT_RESOLVERS",
    "genai_prices_cost",
    "provider_reported_cost",
    "resolve_cost",
]

# Compatibility shim: re-export legacy symbols from the sibling cost.py file
# (shadowed by this package) so existing importers in
# fireflyframework_agentic.observability.__init__ keep working until Phase 8
# of the cost-tracking redesign removes the legacy module.
import importlib.util as _importlib_util  # noqa: E402
import pathlib as _pathlib  # noqa: E402

_legacy_path = _pathlib.Path(__file__).resolve().parent.parent / "cost.py"
if _legacy_path.is_file():
    _spec = _importlib_util.spec_from_file_location(
        "fireflyframework_agentic.observability._cost_legacy", _legacy_path
    )
    if _spec is not None and _spec.loader is not None:
        _legacy = _importlib_util.module_from_spec(_spec)
        _spec.loader.exec_module(_legacy)
        CostCalculator = _legacy.CostCalculator
        GenAIPricesCostCalculator = _legacy.GenAIPricesCostCalculator
        StaticPriceCostCalculator = _legacy.StaticPriceCostCalculator
        get_cost_calculator = _legacy.get_cost_calculator
