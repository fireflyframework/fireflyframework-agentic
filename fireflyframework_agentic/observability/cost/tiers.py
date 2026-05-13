# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""LLM call tier (pricing modifier)."""

from __future__ import annotations

from enum import StrEnum


class CallTier(StrEnum):
    """Pricing tier for an LLM call.

    ``STANDARD`` is the normal synchronous API tier.

    ``BATCH`` represents the asynchronous batch-API tier offered by major
    providers (OpenAI, Anthropic, Google), which is typically billed at
    ~50% of the standard rate. When the underlying pricing source does not
    expose a separate batch rate for the model, :func:`resolve_cost`
    applies a 0.5x post-multiplier as the industry-standard fallback.
    """

    STANDARD = "standard"
    BATCH = "batch"
