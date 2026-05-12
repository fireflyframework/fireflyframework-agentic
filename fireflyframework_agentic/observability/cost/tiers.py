# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""LLM call tier (pricing modifier)."""

from __future__ import annotations

from enum import StrEnum


class CallTier(StrEnum):
    """Pricing tier for an LLM call.

    ``BATCH`` is honored by :func:`resolve_cost` as a 0.5x multiplier when
    the resolver does not natively price the tier.
    """

    STANDARD = "standard"
    BATCH = "batch"
