# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Calendar-aligned window bucket-key helper.

Shared by :class:`~fireflyframework_agentic.observability.budget.BudgetGate`
and :class:`~fireflyframework_agentic.observability.quota.RateLimiter` so the
windowing math lives in exactly one place.
"""

from __future__ import annotations

from datetime import datetime


def bucket_key(window: str, moment: datetime) -> str:
    """Return the bucket key for ``moment`` under ``window``.

    Parameters:
        window: One of ``"lifetime"``, ``"monthly"``, ``"daily"``.
        moment: A timezone-aware datetime (must carry tzinfo).

    Returns:
        ``"lifetime"`` | ``"YYYY-MM"`` | ``"YYYY-MM-DD"``.
    """
    if moment.tzinfo is None:
        raise ValueError("bucket_key requires a timezone-aware datetime")
    if window == "lifetime":
        return "lifetime"
    if window == "monthly":
        return f"{moment.year:04d}-{moment.month:02d}"
    if window == "daily":
        return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
    raise ValueError(f"unknown window: {window!r}")
