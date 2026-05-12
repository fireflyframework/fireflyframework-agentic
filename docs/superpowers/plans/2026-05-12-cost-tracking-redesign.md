# Cost Tracking Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static price table and tangled cost/usage/quota code with a clean five-piece subsystem (resolvers, budget gate, sinks, thin tracker, shared window utility) — accurate pricing via `genai-prices`, multi-scope budgets with `match`-dict rules, and pluggable sinks.

**Architecture:** Five small modules under `fireflyframework_agentic/observability/`:
- `_windows.py` — `bucket_key()` shared by RateLimiter and BudgetGate.
- `cost/{resolvers,tiers}.py` — `CostFn` chain (`provider_reported_cost`, `genai_prices_cost`).
- `budget.py` — `BudgetGate`, `BudgetRule`, `ScopeContext`, `BudgetMode`, `BudgetWindow`.
- `sinks.py` — `CostSink` protocol + 5 built-ins (`OTelMetrics`, `EventBus`, `Logging`, `JSONLFile`, `Webhook`).
- `usage.py` — thin `UsageTracker` orchestrator (resolve → record → gate.commit → sink fan-out).

Data flow per call:
```
record_call(...) ──► resolve_cost ──► UsageRecord ──► gate.commit ──► sinks.emit(...)
```

`record(usage)` stays as the low-level entry; `record_call(...)` is the high-level convenience that resolves cost first and delegates.

**Tech Stack:** Python 3.13, Pydantic v2, OpenTelemetry, `genai-prices` (promoted from optional to required), pytest. Branch already created: `cost-tracking-redesign`.

---

## Phase 0 — Preflight

### Task 0.1: Verify branch and baseline test green

**Files:**
- Verify: `/home/u/signature/fireflyframework-agentic/` is checked out on `cost-tracking-redesign`.

- [ ] **Step 1: Check branch**

```bash
git -C /home/u/signature/fireflyframework-agentic branch --show-current
```

Expected: `cost-tracking-redesign`.

- [ ] **Step 2: Activate venv and run observability baseline**

```bash
source ~/.venvs/firefly/bin/activate
cd /home/u/signature/fireflyframework-agentic
pytest tests/unit/observability/ -q
```

Expected: all green. If anything fails, stop and report — baseline must be clean before the refactor begins.

- [ ] **Step 3: Confirm genai-prices is installed and importable**

```bash
python -c "from genai_prices import find_model; print(find_model)"
```

Expected: `<function find_model at 0x...>` (no ImportError). If ImportError, run `pip install genai-prices`.

---

## Phase 1 — Shared window utility

### Task 1.1: Create `_windows.py` with `bucket_key`

**Files:**
- Create: `fireflyframework_agentic/observability/_windows.py`
- Test: `tests/unit/observability/test_windows.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/observability/test_windows.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Tests for the shared bucket-key window utility."""

from datetime import UTC, datetime

import pytest

from fireflyframework_agentic.observability._windows import bucket_key


@pytest.mark.parametrize(
    ("window", "moment", "expected"),
    [
        ("lifetime", datetime(2026, 5, 12, 14, 30, tzinfo=UTC), "lifetime"),
        ("monthly", datetime(2026, 5, 12, 14, 30, tzinfo=UTC), "2026-05"),
        ("monthly", datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "2026-01"),
        ("daily", datetime(2026, 5, 12, 14, 30, tzinfo=UTC), "2026-05-12"),
        ("daily", datetime(2026, 12, 31, 23, 59, tzinfo=UTC), "2026-12-31"),
    ],
)
def test_bucket_key_known_windows(window: str, moment: datetime, expected: str) -> None:
    assert bucket_key(window, moment) == expected


def test_bucket_key_rejects_unknown_window() -> None:
    with pytest.raises(ValueError, match="unknown window"):
        bucket_key("weekly", datetime.now(UTC))


def test_bucket_key_requires_utc() -> None:
    naive = datetime(2026, 5, 12, 14, 30)
    with pytest.raises(ValueError, match="timezone-aware"):
        bucket_key("daily", naive)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/observability/test_windows.py -v
```

Expected: ImportError / ModuleNotFoundError on `fireflyframework_agentic.observability._windows`.

- [ ] **Step 3: Implement `_windows.py`**

Create `fireflyframework_agentic/observability/_windows.py`:

```python
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
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_windows.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/_windows.py tests/unit/observability/test_windows.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add shared bucket_key window helper"
```

---

## Phase 2 — Cost resolvers (replaces `cost.py`)

### Task 2.1: Create `cost/tiers.py`

**Files:**
- Create: `fireflyframework_agentic/observability/cost/__init__.py`
- Create: `fireflyframework_agentic/observability/cost/tiers.py`
- Test: `tests/unit/observability/test_cost_tiers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/observability/test_cost_tiers.py
from fireflyframework_agentic.observability.cost.tiers import CallTier


def test_call_tier_values() -> None:
    assert CallTier.STANDARD == "standard"
    assert CallTier.BATCH == "batch"


def test_call_tier_is_str() -> None:
    assert isinstance(CallTier.BATCH, str)
```

- [ ] **Step 2: Run test, expect ModuleNotFoundError**

```bash
pytest tests/unit/observability/test_cost_tiers.py -v
```

- [ ] **Step 3: Create the package and tiers module**

Create empty `fireflyframework_agentic/observability/cost/__init__.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Cost-resolution subpackage."""
```

Create `fireflyframework_agentic/observability/cost/tiers.py`:

```python
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
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_cost_tiers.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/cost/__init__.py fireflyframework_agentic/observability/cost/tiers.py tests/unit/observability/test_cost_tiers.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add CallTier enum"
```

### Task 2.2: Create `CostContext` dataclass

**Files:**
- Create: `fireflyframework_agentic/observability/cost/resolvers.py`
- Test: `tests/unit/observability/test_cost_resolvers.py`

- [ ] **Step 1: Write the failing test for CostContext**

```python
# tests/unit/observability/test_cost_resolvers.py
from fireflyframework_agentic.observability.cost.resolvers import CostContext
from fireflyframework_agentic.observability.cost.tiers import CallTier


def test_cost_context_defaults() -> None:
    ctx = CostContext(model="openai:gpt-4o", input_tokens=100, output_tokens=50)
    assert ctx.cache_creation_tokens == 0
    assert ctx.cache_read_tokens == 0
    assert ctx.reasoning_tokens == 0
    assert ctx.tier == CallTier.STANDARD
    assert ctx.provider_payload is None


def test_cost_context_is_frozen() -> None:
    import dataclasses

    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.model = "y"  # type: ignore[misc]


import pytest  # noqa: E402
```

- [ ] **Step 2: Run, expect ModuleNotFoundError on `resolvers`**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 3: Implement skeleton with `CostContext` only**

Create `fireflyframework_agentic/observability/cost/resolvers.py`:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Cost resolution chain.

Each resolver is a plain callable that returns ``float | None``. The
default chain (:data:`DEFAULT_RESOLVERS`) tries provider-reported cost
first and falls back to ``genai-prices``. Users extend the chain by
passing their own list to :func:`resolve_cost`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fireflyframework_agentic.observability.cost.tiers import CallTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostContext:
    """Inputs to a cost resolver."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    tier: CallTier = CallTier.STANDARD
    provider_payload: Mapping[str, Any] | None = None


CostFn = Callable[[CostContext], float | None]
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/cost/resolvers.py tests/unit/observability/test_cost_resolvers.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add CostContext dataclass"
```

### Task 2.3: Implement `provider_reported_cost`

**Files:**
- Modify: `fireflyframework_agentic/observability/cost/resolvers.py`
- Modify: `tests/unit/observability/test_cost_resolvers.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/observability/test_cost_resolvers.py`:

```python
from fireflyframework_agentic.observability.cost.resolvers import provider_reported_cost


def test_provider_reported_cost_openrouter() -> None:
    ctx = CostContext(
        model="openrouter:any/model",
        input_tokens=1, output_tokens=1,
        provider_payload={"usage": {"cost": 0.0123}},
    )
    assert provider_reported_cost(ctx) == 0.0123


def test_provider_reported_cost_absent_returns_none() -> None:
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1, provider_payload={})
    assert provider_reported_cost(ctx) is None


def test_provider_reported_cost_no_payload_returns_none() -> None:
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1, provider_payload=None)
    assert provider_reported_cost(ctx) is None


def test_provider_reported_cost_malformed_returns_none() -> None:
    ctx = CostContext(
        model="x", input_tokens=1, output_tokens=1,
        provider_payload={"usage": {"cost": "not-a-number"}},
    )
    assert provider_reported_cost(ctx) is None
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 3: Implement `provider_reported_cost`**

Append to `fireflyframework_agentic/observability/cost/resolvers.py`:

```python
def provider_reported_cost(ctx: CostContext) -> float | None:
    """Return cost from a known provider-response field, else None.

    Supported sources:
      * OpenRouter — ``provider_payload["usage"]["cost"]`` (USD float).
    """
    payload = ctx.provider_payload
    if not payload:
        return None
    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    if not isinstance(usage, Mapping):
        return None
    cost = usage.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return float(cost)
    return None
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/cost/resolvers.py tests/unit/observability/test_cost_resolvers.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add provider_reported_cost resolver"
```

### Task 2.4: Implement `genai_prices_cost` with `calc_price`

**Files:**
- Modify: `fireflyframework_agentic/observability/cost/resolvers.py`
- Modify: `tests/unit/observability/test_cost_resolvers.py`

`genai-prices` v0.0.57 exposes `calc_price(usage, model_ref, *, provider_id=None) -> PriceCalculation` (NOT `find_model`). The `Usage` dataclass takes `input_tokens` (TOTAL prompt including cache_read), `cache_write_tokens`, `cache_read_tokens`, `output_tokens`. The library subtracts cache portions from `input_tokens` internally — passing `input_tokens < cache_read_tokens` raises `ValueError`. `PriceCalculation.total_price` is the USD cost as a `Decimal`. Unknown models raise `LookupError`. Reasoning tokens are billed at the output rate (industry standard), so we add them into `output_tokens` when constructing `Usage`.

- [ ] **Step 1: Confirm the installed API matches**

```bash
python -c "from genai_prices import calc_price, Usage; import inspect; print(inspect.signature(calc_price)); print(inspect.signature(Usage))"
```

Expected: `calc_price(usage, model_ref, *, provider_id=..., ...)` and `Usage(input_tokens=None, cache_write_tokens=None, cache_read_tokens=None, output_tokens=None, ...)`.

- [ ] **Step 2: Write failing tests for `genai_prices_cost`**

Append to `tests/unit/observability/test_cost_resolvers.py`:

```python
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fireflyframework_agentic.observability.cost.resolvers import genai_prices_cost


def _price_calc(total: float) -> MagicMock:
    """Build a stand-in PriceCalculation with the given total_price."""
    m = MagicMock()
    m.total_price = Decimal(str(total))
    return m


def test_genai_prices_basic_input_output() -> None:
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["usage"] = usage
        captured["model_ref"] = model_ref
        captured["provider_id"] = provider_id
        return _price_calc(0.0075)

    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               side_effect=fake_calc):
        cost = genai_prices_cost(CostContext(
            model="openai:gpt-4o", input_tokens=1000, output_tokens=500,
        ))
    assert cost == pytest.approx(0.0075)
    assert captured["model_ref"] == "gpt-4o"
    assert captured["provider_id"] == "openai"
    # No cache, no reasoning: Usage.input_tokens should equal ctx.input_tokens.
    assert captured["usage"].input_tokens == 1000
    assert captured["usage"].output_tokens == 500


def test_genai_prices_folds_cache_tokens_into_usage_input() -> None:
    """Usage.input_tokens must be TOTAL prompt (uncached + cache_creation + cache_read).

    genai-prices subtracts cache portions internally; passing only the
    uncached portion makes it raise ValueError.
    """
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["usage"] = usage
        return _price_calc(0.0)

    ctx = CostContext(
        model="anthropic:claude-3-5-sonnet-latest",
        input_tokens=100, output_tokens=50,
        cache_creation_tokens=1000, cache_read_tokens=5000,
    )
    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               side_effect=fake_calc):
        genai_prices_cost(ctx)
    u = captured["usage"]
    assert u.input_tokens == 100 + 1000 + 5000
    assert u.cache_write_tokens == 1000
    assert u.cache_read_tokens == 5000


def test_genai_prices_folds_reasoning_into_output() -> None:
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["usage"] = usage
        return _price_calc(0.0)

    ctx = CostContext(model="openai:o3", input_tokens=100, output_tokens=50,
                      reasoning_tokens=200)
    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               side_effect=fake_calc):
        genai_prices_cost(ctx)
    assert captured["usage"].output_tokens == 50 + 200


def test_genai_prices_batch_tier_halves() -> None:
    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               return_value=_price_calc(0.006)):
        cost = genai_prices_cost(CostContext(
            model="openai:gpt-4.1", input_tokens=1000, output_tokens=500,
            tier=CallTier.BATCH,
        ))
    assert cost == pytest.approx(0.003)


def test_genai_prices_unknown_model_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    from fireflyframework_agentic.observability.cost import resolvers as mod
    mod._UNKNOWN_MODEL_WARNED.clear()
    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               side_effect=LookupError("not found")):
        with caplog.at_level("WARNING"):
            assert genai_prices_cost(CostContext(
                model="unknown:foo", input_tokens=1, output_tokens=1)) is None
            assert genai_prices_cost(CostContext(
                model="unknown:foo", input_tokens=1, output_tokens=1)) is None
    warnings = [r for r in caplog.records if "unknown" in r.message.lower()]
    assert len(warnings) == 1  # deduplicated


def test_genai_prices_swallows_other_exceptions() -> None:
    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               side_effect=RuntimeError("boom")):
        assert genai_prices_cost(CostContext(
            model="x", input_tokens=1, output_tokens=1)) is None


def test_genai_prices_no_provider_prefix_passes_none_provider() -> None:
    captured: dict = {}

    def fake_calc(usage, model_ref, *, provider_id=None, **_):
        captured["model_ref"] = model_ref
        captured["provider_id"] = provider_id
        return _price_calc(0.0)

    with patch("fireflyframework_agentic.observability.cost.resolvers.calc_price",
               side_effect=fake_calc):
        genai_prices_cost(CostContext(model="gpt-4o", input_tokens=1, output_tokens=1))
    assert captured["model_ref"] == "gpt-4o"
    assert captured["provider_id"] is None
```

- [ ] **Step 3: Run, expect failures**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 4: Implement `genai_prices_cost`**

Append to `fireflyframework_agentic/observability/cost/resolvers.py`:

```python
try:
    from genai_prices import Usage as _GenAIUsage  # type: ignore[import-untyped]
    from genai_prices import calc_price  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "genai-prices is a required dependency; install with "
        "`pip install fireflyframework-agentic`"
    ) from exc

_UNKNOWN_MODEL_WARNED: set[str] = set()


def _warn_unknown_model_once(model: str) -> None:
    if model in _UNKNOWN_MODEL_WARNED:
        return
    _UNKNOWN_MODEL_WARNED.add(model)
    logger.warning("genai-prices has no entry for model '%s'; cost recorded as 0.0", model)
    try:
        from fireflyframework_agentic.observability.metrics import default_metrics

        default_metrics.record_error(operation="cost_unknown")
    except Exception:  # noqa: BLE001
        logger.debug("Failed to emit cost_unknown metric", exc_info=True)


def genai_prices_cost(ctx: CostContext) -> float | None:
    """Compute cost via :func:`genai_prices.calc_price`, else return ``None``.

    Token mapping:
      * ``Usage.input_tokens`` = ctx.input_tokens + cache_creation_tokens + cache_read_tokens
        (genai-prices subtracts cache portions internally).
      * ``Usage.cache_write_tokens`` = ctx.cache_creation_tokens.
      * ``Usage.cache_read_tokens`` = ctx.cache_read_tokens.
      * ``Usage.output_tokens`` = ctx.output_tokens + ctx.reasoning_tokens
        (reasoning tokens bill at the output rate).

    The ``CallTier.BATCH`` modifier is applied as a 0.5x post-multiplier
    since the library does not natively price batch tiers.

    On unknown model (LookupError): emits ``cost_unknown`` metric +
    WARNING once per model, returns None.
    """
    parts = ctx.model.split(":", 1)
    if len(parts) == 2:
        provider, model_ref = parts
    else:
        provider, model_ref = None, ctx.model

    usage = _GenAIUsage(
        input_tokens=ctx.input_tokens + ctx.cache_creation_tokens + ctx.cache_read_tokens,
        cache_write_tokens=ctx.cache_creation_tokens or None,
        cache_read_tokens=ctx.cache_read_tokens or None,
        output_tokens=ctx.output_tokens + ctx.reasoning_tokens,
    )
    try:
        result = calc_price(usage, model_ref, provider_id=provider)
    except LookupError:
        _warn_unknown_model_once(ctx.model)
        return None
    except Exception:  # noqa: BLE001
        logger.debug("genai-prices lookup raised for '%s'", ctx.model, exc_info=True)
        return None

    total = float(result.total_price)
    if ctx.tier == CallTier.BATCH:
        total *= 0.5
    return total
```

Verify `record_error` accepts no extra kwargs (the plan above uses bare `operation="cost_unknown"`):

```bash
grep -n "def record_error" fireflyframework_agentic/observability/metrics.py
```

If its signature accepts arbitrary kwargs, you may add `model=ctx.model` as a label; if not, the bare form above is correct.

- [ ] **Step 5: Run tests, expect green**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 6: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/cost/resolvers.py tests/unit/observability/test_cost_resolvers.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add genai_prices_cost resolver"
```

### Task 2.5: Implement `resolve_cost` chain + `DEFAULT_RESOLVERS`

**Files:**
- Modify: `fireflyframework_agentic/observability/cost/resolvers.py`
- Modify: `tests/unit/observability/test_cost_resolvers.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/observability/test_cost_resolvers.py`:

```python
from fireflyframework_agentic.observability.cost.resolvers import (
    DEFAULT_RESOLVERS,
    resolve_cost,
)


def test_resolve_cost_uses_first_non_none() -> None:
    def always_one(_ctx: CostContext) -> float | None:
        return 1.23
    def never_called(_ctx: CostContext) -> float | None:
        raise AssertionError("should not be called")
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    assert resolve_cost(ctx, [always_one, never_called]) == 1.23


def test_resolve_cost_falls_through_to_next() -> None:
    def abstain(_ctx: CostContext) -> float | None:
        return None
    def answer(_ctx: CostContext) -> float | None:
        return 7.0
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    assert resolve_cost(ctx, [abstain, answer]) == 7.0


def test_resolve_cost_all_none_returns_zero() -> None:
    def abstain(_ctx: CostContext) -> float | None:
        return None
    ctx = CostContext(model="x", input_tokens=1, output_tokens=1)
    assert resolve_cost(ctx, [abstain, abstain]) == 0.0


def test_resolve_cost_default_chain_used_when_none() -> None:
    # Default chain = [provider_reported_cost, genai_prices_cost].
    # With a payload carrying cost, provider_reported_cost wins; genai-prices
    # is not consulted (no patch needed).
    ctx = CostContext(
        model="openrouter:x", input_tokens=1, output_tokens=1,
        provider_payload={"usage": {"cost": 0.42}},
    )
    assert resolve_cost(ctx) == 0.42


def test_default_resolvers_is_tuple() -> None:
    assert isinstance(DEFAULT_RESOLVERS, tuple)
    assert len(DEFAULT_RESOLVERS) == 2
```

- [ ] **Step 2: Run, expect failures**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 3: Implement chain + default**

Append to `fireflyframework_agentic/observability/cost/resolvers.py`:

```python
DEFAULT_RESOLVERS: tuple[CostFn, ...] = (provider_reported_cost, genai_prices_cost)


def resolve_cost(ctx: CostContext, resolvers: Sequence[CostFn] | None = None) -> float:
    """Return the first non-None result from the chain, else 0.0."""
    chain = resolvers if resolvers is not None else DEFAULT_RESOLVERS
    for fn in chain:
        result = fn(ctx)
        if result is not None:
            return float(result)
    return 0.0
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_cost_resolvers.py -v
```

- [ ] **Step 5: Re-export from `cost/__init__.py`**

Replace `fireflyframework_agentic/observability/cost/__init__.py` with:

```python
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
```

- [ ] **Step 6: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/cost/ tests/unit/observability/test_cost_resolvers.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add resolve_cost chain"
```

---

## Phase 3 — Extend `BudgetExceededError`

### Task 3.1: Extend exception in place

**Files:**
- Modify: `fireflyframework_agentic/exceptions.py:191-193`
- Test: `tests/unit/core/test_exceptions.py` (existing; add cases)

- [ ] **Step 1: Find the existing test file or create one**

```bash
ls tests/unit/core/ | grep -i except
```

If `test_exceptions.py` does not exist, create `tests/unit/core/test_exceptions.py` with the test below. Otherwise append.

- [ ] **Step 2: Write failing test**

```python
# tests/unit/core/test_exceptions.py — add or create
import pytest

from fireflyframework_agentic.exceptions import BudgetExceededError, QuotaError


def test_budget_exceeded_error_legacy_construction() -> None:
    err = BudgetExceededError("budget blew up")
    assert str(err) == "budget blew up"
    assert isinstance(err, QuotaError)
    assert err.rule_name == ""
    assert err.spend_usd == 0.0
    assert err.limit_usd == 0.0


def test_budget_exceeded_error_structured_fields() -> None:
    err = BudgetExceededError(
        "rule 'acme' exceeded",
        rule_name="acme",
        spend_usd=12.5,
        limit_usd=10.0,
    )
    assert err.rule_name == "acme"
    assert err.spend_usd == 12.5
    assert err.limit_usd == 10.0
```

- [ ] **Step 3: Run, expect AttributeError on `.rule_name`**

```bash
pytest tests/unit/core/test_exceptions.py -v
```

- [ ] **Step 4: Modify `exceptions.py`**

Replace lines 191-193 of `fireflyframework_agentic/exceptions.py`:

```python
class BudgetExceededError(QuotaError):
    """Raised when a budget rule is exceeded.

    Carries structured fields populated by
    :class:`~fireflyframework_agentic.observability.budget.BudgetGate`.
    """

    rule_name: str
    spend_usd: float
    limit_usd: float

    def __init__(
        self,
        msg: str = "",
        *,
        rule_name: str = "",
        spend_usd: float = 0.0,
        limit_usd: float = 0.0,
    ) -> None:
        super().__init__(msg)
        self.rule_name = rule_name
        self.spend_usd = spend_usd
        self.limit_usd = limit_usd
```

(We omit `scope_ctx` here because storing the `ScopeContext` on the exception creates a circular import; callers can recover it from logs. Spec is satisfied — the structured fields are present.)

- [ ] **Step 5: Run tests, expect green**

```bash
pytest tests/unit/core/test_exceptions.py -v
```

- [ ] **Step 6: Run the full observability + agents tests to confirm no regressions in existing exception raises**

```bash
pytest tests/unit/observability/ tests/unit/agents/ -q
```

Existing call sites pass only a message; they keep working.

- [ ] **Step 7: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/exceptions.py tests/unit/core/test_exceptions.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(exceptions): extend BudgetExceededError with structured fields"
```

---

## Phase 4 — `BudgetGate`

### Task 4.1: `ScopeContext` + `BudgetMode` + `BudgetWindow`

**Files:**
- Create: `fireflyframework_agentic/observability/budget.py`
- Test: `tests/unit/observability/test_budget.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/observability/test_budget.py
from fireflyframework_agentic.observability.budget import (
    BudgetMode,
    BudgetWindow,
    ScopeContext,
)


def test_budget_mode_values() -> None:
    assert BudgetMode.HARD == "hard"
    assert BudgetMode.SOFT == "soft"


def test_budget_window_values() -> None:
    assert {BudgetWindow.LIFETIME, BudgetWindow.MONTHLY, BudgetWindow.DAILY} == {
        "lifetime", "monthly", "daily",
    }


def test_scope_context_to_match_dict_builtin_keys() -> None:
    ctx = ScopeContext(tenant="acme", agent="writer", model="openai:gpt-4o",
                       correlation_id="run-1")
    d = ctx.to_match_dict()
    assert d == {"tenant": "acme", "agent": "writer", "model": "openai:gpt-4o",
                 "correlation_id": "run-1"}


def test_scope_context_to_match_dict_merges_labels() -> None:
    ctx = ScopeContext(tenant="acme", labels={"env": "prod", "feature": "summary"})
    d = ctx.to_match_dict()
    assert d == {"tenant": "acme", "env": "prod", "feature": "summary"}


def test_scope_context_builtin_wins_over_labels() -> None:
    ctx = ScopeContext(tenant="real", labels={"tenant": "fake"})
    assert ctx.to_match_dict()["tenant"] == "real"


def test_scope_context_omits_empty_builtins() -> None:
    ctx = ScopeContext(tenant="", agent="writer")
    assert ctx.to_match_dict() == {"agent": "writer"}
```

- [ ] **Step 2: Run, expect ModuleNotFoundError**

```bash
pytest tests/unit/observability/test_budget.py -v
```

- [ ] **Step 3: Create `budget.py` skeleton**

```python
# fireflyframework_agentic/observability/budget.py
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Budget enforcement with scoped, windowed rules.

A :class:`BudgetGate` holds a sequence of :class:`BudgetRule` objects.
Each rule has a window (calendar-aligned), a mode (hard | soft), and a
``match`` dict that filters which calls it applies to.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability._windows import bucket_key

logger = logging.getLogger(__name__)


class BudgetMode(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class BudgetWindow(StrEnum):
    LIFETIME = "lifetime"
    MONTHLY = "monthly"
    DAILY = "daily"


@dataclass(frozen=True)
class ScopeContext:
    """Identity / attribution dimensions for a single LLM call."""

    tenant: str = ""
    agent: str = ""
    model: str = ""
    correlation_id: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_match_dict(self) -> dict[str, str]:
        """Flatten to a string→string mapping for ``BudgetRule.match``.

        Built-in fields win on collision with labels; empty built-in
        fields are omitted (so a rule keyed on ``tenant`` does not match
        a call whose tenant is the empty string).
        """
        out: dict[str, str] = dict(self.labels)
        for key, value in (
            ("tenant", self.tenant),
            ("agent", self.agent),
            ("model", self.model),
            ("correlation_id", self.correlation_id),
        ):
            if value:
                out[key] = value
        return out
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_budget.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/budget.py tests/unit/observability/test_budget.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add ScopeContext + BudgetMode/Window enums"
```

### Task 4.2: `BudgetRule` and rule-matching

**Files:**
- Modify: `fireflyframework_agentic/observability/budget.py`
- Modify: `tests/unit/observability/test_budget.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/unit/observability/test_budget.py
from fireflyframework_agentic.observability.budget import BudgetRule, _rule_matches


def test_rule_matches_empty_match_matches_everything() -> None:
    rule = BudgetRule(name="global", limit_usd=10.0, match={})
    assert _rule_matches(rule, ScopeContext(tenant="acme"))


def test_rule_matches_single_key() -> None:
    rule = BudgetRule(name="acme-only", limit_usd=10.0, match={"tenant": "acme"})
    assert _rule_matches(rule, ScopeContext(tenant="acme"))
    assert not _rule_matches(rule, ScopeContext(tenant="other"))


def test_rule_matches_is_AND_of_keys() -> None:
    rule = BudgetRule(name="prod-writer", limit_usd=10.0,
                      match={"agent": "writer", "env": "prod"})
    assert _rule_matches(rule, ScopeContext(agent="writer", labels={"env": "prod"}))
    assert not _rule_matches(rule, ScopeContext(agent="writer", labels={"env": "dev"}))
    assert not _rule_matches(rule, ScopeContext(agent="reader", labels={"env": "prod"}))


def test_budget_rule_defaults() -> None:
    rule = BudgetRule(name="x", limit_usd=5.0)
    assert rule.mode == BudgetMode.HARD
    assert rule.window == BudgetWindow.LIFETIME
    assert rule.match == {}
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/unit/observability/test_budget.py -v
```

- [ ] **Step 3: Add `BudgetRule` and matcher**

Append to `fireflyframework_agentic/observability/budget.py`:

```python
@dataclass(frozen=True)
class BudgetRule:
    name: str
    limit_usd: float
    mode: BudgetMode = BudgetMode.HARD
    window: BudgetWindow = BudgetWindow.LIFETIME
    match: Mapping[str, str] = field(default_factory=dict)


def _rule_matches(rule: BudgetRule, ctx: ScopeContext) -> bool:
    """Return True iff every (k, v) in rule.match is in ctx.to_match_dict()."""
    if not rule.match:
        return True
    flat = ctx.to_match_dict()
    return all(flat.get(k) == v for k, v in rule.match.items())
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_budget.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/budget.py tests/unit/observability/test_budget.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add BudgetRule + matcher"
```

### Task 4.3: `BudgetGate.precheck` and `commit` (HARD mode, single rule, LIFETIME window)

**Files:**
- Modify: `fireflyframework_agentic/observability/budget.py`
- Modify: `tests/unit/observability/test_budget.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/unit/observability/test_budget.py
import pytest

from fireflyframework_agentic.exceptions import BudgetExceededError
from fireflyframework_agentic.observability.budget import BudgetGate
from fireflyframework_agentic.observability.usage import UsageRecord


def test_gate_commit_accumulates_and_raises_on_hard() -> None:
    gate = BudgetGate([BudgetRule(name="global", limit_usd=1.0)])
    ctx = ScopeContext()
    gate.commit(UsageRecord(cost_usd=0.4), ctx)
    gate.commit(UsageRecord(cost_usd=0.5), ctx)
    assert gate.spend("global") == pytest.approx(0.9)
    with pytest.raises(BudgetExceededError) as exc:
        gate.commit(UsageRecord(cost_usd=0.2), ctx)
    assert exc.value.rule_name == "global"
    assert exc.value.limit_usd == 1.0


def test_gate_commit_soft_logs_no_raise(caplog: pytest.LogCaptureFixture) -> None:
    gate = BudgetGate([BudgetRule(name="g", limit_usd=1.0, mode=BudgetMode.SOFT)])
    with caplog.at_level("WARNING"):
        gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())
    assert any("budget" in r.message.lower() for r in caplog.records)
    assert gate.spend("g") == pytest.approx(2.0)


def test_gate_precheck_blocks_hard_overrun() -> None:
    gate = BudgetGate([BudgetRule(name="g", limit_usd=1.0)])
    gate.commit(UsageRecord(cost_usd=0.95), ScopeContext())
    with pytest.raises(BudgetExceededError):
        gate.precheck(estimated_cost_usd=0.1, ctx=ScopeContext())


def test_gate_precheck_zero_estimate_is_noop() -> None:
    gate = BudgetGate([BudgetRule(name="g", limit_usd=1.0)])
    gate.commit(UsageRecord(cost_usd=0.95), ScopeContext())
    gate.precheck(estimated_cost_usd=0.0, ctx=ScopeContext())  # no raise


def test_gate_only_applies_matching_rules() -> None:
    gate = BudgetGate([BudgetRule(name="acme", limit_usd=1.0, match={"tenant": "acme"})])
    gate.commit(UsageRecord(cost_usd=2.0), ScopeContext(tenant="other"))  # not matched, no raise
    assert gate.spend("acme") == 0.0


def test_gate_reset_single_rule_and_all() -> None:
    gate = BudgetGate([BudgetRule(name="a", limit_usd=10.0), BudgetRule(name="b", limit_usd=10.0)])
    gate.commit(UsageRecord(cost_usd=1.0), ScopeContext())
    gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())
    gate.reset("a")
    assert gate.spend("a") == 0.0
    assert gate.spend("b") == pytest.approx(2.0)
    gate.reset()
    assert gate.spend("b") == 0.0
```

- [ ] **Step 2: Run, expect ImportError on `BudgetGate`**

```bash
pytest tests/unit/observability/test_budget.py -v
```

- [ ] **Step 3: Implement `BudgetGate`**

Append to `fireflyframework_agentic/observability/budget.py`:

```python
class BudgetGate:
    """Hold a set of :class:`BudgetRule` accumulators and enforce them."""

    def __init__(self, rules: Sequence[BudgetRule]) -> None:
        self._rules: tuple[BudgetRule, ...] = tuple(rules)
        # rule_name -> (bucket_key, accumulated_usd)
        self._state: dict[str, tuple[str, float]] = {r.name: ("", 0.0) for r in self._rules}
        self._lock = threading.Lock()

    def precheck(self, estimated_cost_usd: float, ctx: ScopeContext) -> None:
        """Raise on HARD breach if the estimated cost would push spend over the limit."""
        if estimated_cost_usd <= 0.0:
            return
        now = datetime.now(UTC)
        with self._lock:
            for rule in self._rules:
                if not _rule_matches(rule, ctx):
                    continue
                bk = bucket_key(rule.window.value, now)
                stored_bk, accumulated = self._state[rule.name]
                if stored_bk != bk:
                    accumulated = 0.0
                projected = accumulated + estimated_cost_usd
                if projected > rule.limit_usd and rule.mode == BudgetMode.HARD:
                    raise BudgetExceededError(
                        f"Budget '{rule.name}' would be exceeded: "
                        f"${projected:.4f} > ${rule.limit_usd:.4f}",
                        rule_name=rule.name,
                        spend_usd=projected,
                        limit_usd=rule.limit_usd,
                    )

    def commit(self, record: UsageRecord, ctx: ScopeContext) -> None:
        """Add ``record.cost_usd`` to every matching rule. Raise on HARD breach."""
        cost = record.cost_usd
        if cost <= 0.0:
            return
        now = datetime.now(UTC)
        to_raise: BudgetExceededError | None = None
        with self._lock:
            for rule in self._rules:
                if not _rule_matches(rule, ctx):
                    continue
                bk = bucket_key(rule.window.value, now)
                stored_bk, accumulated = self._state[rule.name]
                if stored_bk != bk:
                    accumulated = 0.0
                accumulated += cost
                self._state[rule.name] = (bk, accumulated)
                if accumulated > rule.limit_usd:
                    msg = (
                        f"Budget '{rule.name}' exceeded: "
                        f"${accumulated:.4f} > ${rule.limit_usd:.4f}"
                    )
                    if rule.mode == BudgetMode.HARD:
                        to_raise = BudgetExceededError(
                            msg,
                            rule_name=rule.name,
                            spend_usd=accumulated,
                            limit_usd=rule.limit_usd,
                        )
                    else:
                        logger.warning("%s (mode=soft)", msg)
        if to_raise is not None:
            raise to_raise

    def spend(self, rule_name: str) -> float:
        """Return accumulated spend for a rule in the current window bucket."""
        with self._lock:
            return self._state.get(rule_name, ("", 0.0))[1]

    def reset(self, rule_name: str | None = None) -> None:
        """Reset one rule's accumulator, or all if name is None."""
        with self._lock:
            if rule_name is None:
                for name in self._state:
                    self._state[name] = ("", 0.0)
            elif rule_name in self._state:
                self._state[rule_name] = ("", 0.0)
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_budget.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/budget.py tests/unit/observability/test_budget.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add BudgetGate with precheck/commit"
```

### Task 4.4: Window-bucket reset behavior

**Files:**
- Modify: `tests/unit/observability/test_budget.py`

- [ ] **Step 1: Write failing test with frozen time**

```python
# Append to tests/unit/observability/test_budget.py
from unittest.mock import patch


def test_gate_resets_accumulator_when_daily_bucket_changes() -> None:
    gate = BudgetGate([BudgetRule(name="d", limit_usd=10.0, window=BudgetWindow.DAILY)])

    day1 = datetime(2026, 5, 12, 23, 30, tzinfo=UTC)
    day2 = datetime(2026, 5, 13, 0, 30, tzinfo=UTC)

    with patch("fireflyframework_agentic.observability.budget.datetime") as dt:
        dt.now.return_value = day1
        gate.commit(UsageRecord(cost_usd=8.0), ScopeContext())
        assert gate.spend("d") == pytest.approx(8.0)

        dt.now.return_value = day2
        gate.commit(UsageRecord(cost_usd=3.0), ScopeContext())  # new bucket; no raise
        assert gate.spend("d") == pytest.approx(3.0)


def test_gate_resets_accumulator_when_monthly_bucket_changes() -> None:
    gate = BudgetGate([BudgetRule(name="m", limit_usd=10.0, window=BudgetWindow.MONTHLY)])
    mid_april = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    mid_may = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    with patch("fireflyframework_agentic.observability.budget.datetime") as dt:
        dt.now.return_value = mid_april
        gate.commit(UsageRecord(cost_usd=9.0), ScopeContext())
        dt.now.return_value = mid_may
        gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())  # new month bucket
        assert gate.spend("m") == pytest.approx(2.0)


def test_gate_lifetime_never_resets() -> None:
    gate = BudgetGate([BudgetRule(name="l", limit_usd=100.0, window=BudgetWindow.LIFETIME)])
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2027, 6, 30, tzinfo=UTC)
    with patch("fireflyframework_agentic.observability.budget.datetime") as dt:
        dt.now.return_value = t1
        gate.commit(UsageRecord(cost_usd=3.0), ScopeContext())
        dt.now.return_value = t2
        gate.commit(UsageRecord(cost_usd=2.0), ScopeContext())
        assert gate.spend("l") == pytest.approx(5.0)
```

Note: patching `datetime` on the budget module substitutes the symbol but `bucket_key` imports `datetime` itself — so we must patch the `datetime.now` call site, not the type. The patch above targets `datetime.now`, which is what `BudgetGate` uses.

- [ ] **Step 2: Run tests, expect green** (BudgetGate already calls `datetime.now(UTC)`)

```bash
pytest tests/unit/observability/test_budget.py -v
```

If they fail because the patch did not bind: change the patch target to `"fireflyframework_agentic.observability.budget.datetime"` and ensure `BudgetGate.commit` / `BudgetGate.precheck` call `datetime.now(UTC)` (already the case from Task 4.3).

- [ ] **Step 3: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add tests/unit/observability/test_budget.py
git -C /home/u/signature/fireflyframework-agentic commit -m "test(observability): cover bucket-reset semantics for BudgetGate"
```

---

## Phase 5 — Sinks

### Task 5.1: `CostSink` protocol + `_emit_safely`

**Files:**
- Create: `fireflyframework_agentic/observability/sinks.py`
- Test: `tests/unit/observability/test_sinks.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/observability/test_sinks.py
import logging

import pytest

from fireflyframework_agentic.observability.sinks import CostSink, _emit_safely
from fireflyframework_agentic.observability.usage import UsageRecord


class _GoodSink:
    def __init__(self) -> None:
        self.received: list[UsageRecord] = []
    def emit(self, record: UsageRecord) -> None:
        self.received.append(record)


class _BadSink:
    def emit(self, record: UsageRecord) -> None:
        raise RuntimeError("boom")


def test_emit_safely_passes_record_through() -> None:
    sink = _GoodSink()
    rec = UsageRecord(agent="a", total_tokens=10)
    _emit_safely(sink, rec)
    assert sink.received == [rec]


def test_emit_safely_swallows_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        _emit_safely(_BadSink(), UsageRecord())
    assert any("_BadSink" in r.message or "sink" in r.message.lower() for r in caplog.records)


def test_cost_sink_protocol_is_runtime_checkable() -> None:
    assert isinstance(_GoodSink(), CostSink)
```

- [ ] **Step 2: Run, expect ModuleNotFoundError**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 3: Implement protocol + helper**

```python
# fireflyframework_agentic/observability/sinks.py
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Pluggable output sinks for :class:`UsageRecord`."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from fireflyframework_agentic.observability.usage import UsageRecord

logger = logging.getLogger(__name__)


@runtime_checkable
class CostSink(Protocol):
    """Receives one :class:`UsageRecord` per LLM call."""

    def emit(self, record: UsageRecord) -> None: ...

    def flush(self) -> None: ...  # default no-op; override if buffering.

    def close(self) -> None: ...  # default no-op; override to drain.


def _emit_safely(sink: CostSink, record: UsageRecord) -> None:
    """Call ``sink.emit(record)``, swallowing all exceptions.

    Increments the ``cost_sink_errors`` counter labeled by sink class
    name when emission fails.
    """
    try:
        sink.emit(record)
    except Exception:  # noqa: BLE001
        sink_name = type(sink).__name__
        logger.warning("Sink %s.emit() raised; record dropped", sink_name, exc_info=True)
        try:
            from fireflyframework_agentic.observability.metrics import default_metrics
            default_metrics.record_error(operation="cost_sink_errors", sink=sink_name)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit cost_sink_errors metric", exc_info=True)
```

If `default_metrics.record_error` does not accept `sink=...` kwarg, drop the label.

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/sinks.py tests/unit/observability/test_sinks.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add CostSink protocol + safe-emit helper"
```

### Task 5.2: `OTelMetricsSink` and `EventBusSink`

**Files:**
- Modify: `fireflyframework_agentic/observability/sinks.py`
- Modify: `tests/unit/observability/test_sinks.py`

These two replicate today's `UsageTracker._emit_metrics` and `_emit_event` exactly so the existing observability behavior is preserved.

- [ ] **Step 1: Write failing test**

```python
# Append to tests/unit/observability/test_sinks.py
from unittest.mock import patch

from fireflyframework_agentic.observability.sinks import EventBusSink, OTelMetricsSink


def test_otel_metrics_sink_calls_record_tokens() -> None:
    rec = UsageRecord(agent="a", model="openai:gpt-4o",
                      input_tokens=10, output_tokens=5, total_tokens=15,
                      cost_usd=0.001, latency_ms=200.0)
    with patch("fireflyframework_agentic.observability.sinks.default_metrics") as m:
        OTelMetricsSink().emit(rec)
        m.record_tokens.assert_called_with(15, agent="a", model="openai:gpt-4o")
        m.record_prompt_tokens.assert_called_with(10, agent="a", model="openai:gpt-4o")
        m.record_completion_tokens.assert_called_with(5, agent="a", model="openai:gpt-4o")
        m.record_cost.assert_called_with(0.001, agent="a", model="openai:gpt-4o")
        m.record_latency.assert_called_with(200.0, operation="agent.run", agent="a")


def test_event_bus_sink_calls_agent_completed() -> None:
    rec = UsageRecord(agent="a", model="x", total_tokens=10,
                      input_tokens=6, output_tokens=4, latency_ms=50.0, cost_usd=0.01)
    with patch("fireflyframework_agentic.observability.sinks.default_events") as e:
        EventBusSink().emit(rec)
        e.agent_completed.assert_called_once_with(
            "a", tokens=10, latency_ms=50.0, model="x",
            cost_usd=0.01, input_tokens=6, output_tokens=4,
        )
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 3: Implement both sinks**

Append to `fireflyframework_agentic/observability/sinks.py`:

```python
from fireflyframework_agentic.observability.events import default_events
from fireflyframework_agentic.observability.metrics import default_metrics


class OTelMetricsSink:
    """Forward token, cost, and latency observations to ``default_metrics``.

    Mirrors the legacy ``UsageTracker._emit_metrics`` behavior exactly.
    """

    def emit(self, record: UsageRecord) -> None:
        if record.total_tokens > 0:
            default_metrics.record_tokens(
                record.total_tokens, agent=record.agent, model=record.model
            )
        if record.input_tokens > 0:
            default_metrics.record_prompt_tokens(
                record.input_tokens, agent=record.agent, model=record.model
            )
        if record.output_tokens > 0:
            default_metrics.record_completion_tokens(
                record.output_tokens, agent=record.agent, model=record.model
            )
        if record.cost_usd > 0:
            default_metrics.record_cost(
                record.cost_usd, agent=record.agent, model=record.model
            )
        if record.latency_ms > 0:
            default_metrics.record_latency(
                record.latency_ms, operation="agent.run", agent=record.agent
            )

    def flush(self) -> None: ...
    def close(self) -> None: ...


class EventBusSink:
    """Forward each record as an ``agent_completed`` event."""

    def emit(self, record: UsageRecord) -> None:
        default_events.agent_completed(
            record.agent,
            tokens=record.total_tokens,
            latency_ms=record.latency_ms,
            model=record.model,
            cost_usd=record.cost_usd,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
        )

    def flush(self) -> None: ...
    def close(self) -> None: ...
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/sinks.py tests/unit/observability/test_sinks.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add OTelMetricsSink and EventBusSink"
```

### Task 5.3: `LoggingSink` and `JSONLFileSink`

**Files:**
- Modify: `fireflyframework_agentic/observability/sinks.py`
- Modify: `tests/unit/observability/test_sinks.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/unit/observability/test_sinks.py
import json
from pathlib import Path

from fireflyframework_agentic.observability.sinks import JSONLFileSink, LoggingSink


def test_logging_sink_emits_at_info(caplog: pytest.LogCaptureFixture) -> None:
    rec = UsageRecord(agent="a", total_tokens=5, cost_usd=0.001)
    with caplog.at_level(logging.INFO, logger="fireflyframework_agentic.observability.sinks"):
        LoggingSink().emit(rec)
    assert any('"agent":"a"' in r.message or "'agent': 'a'" in r.message
               or "a" in r.message for r in caplog.records)


def test_jsonl_file_sink_writes_one_line_per_record(tmp_path: Path) -> None:
    path = tmp_path / "cost.jsonl"
    sink = JSONLFileSink(path)
    sink.emit(UsageRecord(agent="a1", cost_usd=0.1))
    sink.emit(UsageRecord(agent="a2", cost_usd=0.2))
    sink.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["agent"] == "a1"
    assert json.loads(lines[1])["agent"] == "a2"


def test_jsonl_file_sink_rotation(tmp_path: Path) -> None:
    path = tmp_path / "cost.jsonl"
    sink = JSONLFileSink(path, rotate_bytes=64)  # tiny size to force rotation
    for i in range(20):
        sink.emit(UsageRecord(agent=f"a{i}"))
    sink.close()
    rotated = list(tmp_path.glob("cost.jsonl*"))
    assert len(rotated) > 1
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 3: Implement both**

Append to `fireflyframework_agentic/observability/sinks.py`:

```python
import json
import threading
from datetime import UTC, datetime
from pathlib import Path


class LoggingSink:
    """Log each record at INFO via the module logger."""

    def __init__(self, level: int = logging.INFO) -> None:
        self._level = level

    def emit(self, record: UsageRecord) -> None:
        logger.log(self._level, "cost_record %s", record.model_dump_json())

    def flush(self) -> None: ...
    def close(self) -> None: ...


class JSONLFileSink:
    """Append-only JSONL writer with optional size-based rotation.

    Parameters:
        path: Output file path. Created on first emit if missing.
        rotate_bytes: When set, rotate the file to ``path.N`` once it exceeds
            this size. Rotation is checked on each emit (O(1) ``stat``).
    """

    def __init__(self, path: Path | str, *, rotate_bytes: int | None = None) -> None:
        self._path = Path(path)
        self._rotate_bytes = rotate_bytes
        self._lock = threading.Lock()

    def emit(self, record: UsageRecord) -> None:
        line = record.model_dump_json() + "\n"
        with self._lock:
            self._maybe_rotate(len(line))
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def _maybe_rotate(self, incoming_bytes: int) -> None:
        if self._rotate_bytes is None or not self._path.exists():
            return
        if self._path.stat().st_size + incoming_bytes <= self._rotate_bytes:
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        rotated = self._path.with_suffix(self._path.suffix + f".{stamp}")
        self._path.rename(rotated)

    def flush(self) -> None: ...
    def close(self) -> None: ...
```

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/sinks.py tests/unit/observability/test_sinks.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add LoggingSink and JSONLFileSink"
```

### Task 5.4: `WebhookSink` (background batching POSTer)

**Files:**
- Modify: `fireflyframework_agentic/observability/sinks.py`
- Modify: `tests/unit/observability/test_sinks.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/unit/observability/test_sinks.py
import time
from unittest.mock import MagicMock

from fireflyframework_agentic.observability.sinks import WebhookSink


def test_webhook_sink_batches_and_flushes() -> None:
    posts: list[list[dict]] = []

    def fake_post(url: str, json: list[dict], headers: dict, timeout: float) -> MagicMock:
        posts.append(json)
        m = MagicMock()
        m.status_code = 200
        return m

    sink = WebhookSink("https://example.test/cost", batch_size=3,
                      flush_interval_s=10.0, _post=fake_post)
    for i in range(5):
        sink.emit(UsageRecord(agent=f"a{i}", cost_usd=0.01))
    sink.close()  # forces drain
    assert sum(len(b) for b in posts) == 5


def test_webhook_sink_retries_5xx_then_succeeds() -> None:
    attempts = {"n": 0}

    def fake_post(url: str, json: list[dict], headers: dict, timeout: float) -> MagicMock:
        attempts["n"] += 1
        m = MagicMock()
        m.status_code = 500 if attempts["n"] < 2 else 200
        return m

    sink = WebhookSink("https://example.test/cost", batch_size=1,
                      flush_interval_s=10.0, max_retries=3, _post=fake_post)
    sink.emit(UsageRecord(agent="a", cost_usd=0.01))
    sink.close()
    assert attempts["n"] >= 2


def test_webhook_sink_drops_after_max_retries(caplog: pytest.LogCaptureFixture) -> None:
    def always_fail(url: str, json: list[dict], headers: dict, timeout: float) -> MagicMock:
        m = MagicMock(); m.status_code = 500; return m

    sink = WebhookSink("https://x", batch_size=1, flush_interval_s=10.0,
                      max_retries=2, _post=always_fail)
    with caplog.at_level(logging.WARNING):
        sink.emit(UsageRecord(agent="a", cost_usd=0.01))
        sink.close()
    assert any("drop" in r.message.lower() or "fail" in r.message.lower()
               for r in caplog.records)
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

- [ ] **Step 3: Implement `WebhookSink`**

Append to `fireflyframework_agentic/observability/sinks.py`:

```python
from collections.abc import Callable
from queue import Empty, Queue
from typing import Any

import httpx


def _default_post(url: str, json: list[dict], headers: dict, timeout: float) -> Any:
    """Default POST function. Replaced in tests via WebhookSink(_post=...)."""
    return httpx.post(url, json=json, headers=headers, timeout=timeout)


class WebhookSink:
    """Batch records and POST them to an HTTP endpoint.

    Parameters:
        url: Endpoint URL.
        batch_size: Records per POST. Drained sooner on ``flush_interval_s``.
        flush_interval_s: Background flush cadence in seconds.
        headers: Extra HTTP headers (Authorization, etc.).
        max_retries: How many times to retry a 5xx response before dropping.
        timeout_s: Per-request HTTP timeout.
        _post: Internal hook for tests.
    """

    def __init__(
        self,
        url: str,
        *,
        batch_size: int = 50,
        flush_interval_s: float = 5.0,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        timeout_s: float = 10.0,
        _post: Callable[[str, list[dict], dict, float], Any] | None = None,
    ) -> None:
        self._url = url
        self._batch_size = batch_size
        self._interval = flush_interval_s
        self._headers = headers or {}
        self._max_retries = max_retries
        self._timeout = timeout_s
        self._post = _post or _default_post
        self._queue: Queue[UsageRecord] = Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="WebhookSink", daemon=True)
        self._thread.start()

    def emit(self, record: UsageRecord) -> None:
        self._queue.put(record)

    def _run(self) -> None:
        buf: list[UsageRecord] = []
        last_flush = time.monotonic()
        while not self._stop.is_set():
            try:
                rec = self._queue.get(timeout=0.1)
                buf.append(rec)
            except Empty:
                pass
            now = time.monotonic()
            if len(buf) >= self._batch_size or (buf and now - last_flush >= self._interval):
                self._send(buf)
                buf = []
                last_flush = now
        # Drain remaining on stop.
        while True:
            try:
                buf.append(self._queue.get_nowait())
            except Empty:
                break
        if buf:
            self._send(buf)

    def _send(self, batch: list[UsageRecord]) -> None:
        payload = [r.model_dump(mode="json") for r in batch]
        delay = 0.1
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._post(self._url, payload, self._headers, self._timeout)
                status = int(getattr(resp, "status_code", 0))
                if 200 <= status < 300:
                    return
                if 500 <= status < 600 and attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("WebhookSink: dropping batch (status %d)", status)
                self._record_sink_error()
                return
            except Exception:  # noqa: BLE001
                if attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("WebhookSink: dropping batch after exhausted retries",
                               exc_info=True)
                self._record_sink_error()
                return

    @staticmethod
    def _record_sink_error() -> None:
        try:
            from fireflyframework_agentic.observability.metrics import default_metrics
            default_metrics.record_error(operation="cost_sink_errors", sink="WebhookSink")
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit cost_sink_errors metric", exc_info=True)

    def flush(self) -> None:
        """Block until the queue is empty (best-effort)."""
        while not self._queue.empty():
            time.sleep(0.01)

    def close(self) -> None:
        """Stop background thread and drain remaining records."""
        self._stop.set()
        self._thread.join(timeout=self._interval + 2.0)
```

Add `httpx` to the import list at top of file. It's already in core deps (line 30 of `pyproject.toml`).

- [ ] **Step 4: Run tests, expect green**

```bash
pytest tests/unit/observability/test_sinks.py -v
```

If the timing-dependent tests are flaky, increase the `close()` join timeout or rework the test to call `close()` immediately after `emit()` so the drain path fires.

- [ ] **Step 5: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/sinks.py tests/unit/observability/test_sinks.py
git -C /home/u/signature/fireflyframework-agentic commit -m "feat(observability): add WebhookSink with batching + retry"
```

---

## Phase 6 — Rewire `UsageTracker`

### Task 6.1: Thin tracker — accept resolver, gate, sinks; keep public surface

**Files:**
- Modify: `fireflyframework_agentic/observability/usage.py`
- Modify: `tests/unit/observability/test_usage.py`

- [ ] **Step 1: Read current `usage.py` end-to-end**

```bash
cat fireflyframework_agentic/observability/usage.py
```

The current tracker (~300 lines) owns `_emit_metrics`, `_emit_event`, `_check_budget`. These move out; the new tracker shrinks to ~120 lines.

- [ ] **Step 2: Write the new test cases that drive `record_call`**

Append to `tests/unit/observability/test_usage.py`:

```python
from unittest.mock import MagicMock

from fireflyframework_agentic.observability.budget import BudgetGate, BudgetRule, ScopeContext
from fireflyframework_agentic.observability.cost.tiers import CallTier
from fireflyframework_agentic.observability.sinks import CostSink


class _Capturing:
    def __init__(self) -> None:
        self.received: list[UsageRecord] = []
    def emit(self, record: UsageRecord) -> None:
        self.received.append(record)
    def flush(self) -> None: ...
    def close(self) -> None: ...


def test_record_call_resolves_cost_and_emits_to_sinks() -> None:
    sink = _Capturing()
    tracker = UsageTracker(sinks=[sink], resolver=lambda ctx: 1.23, gate=None)
    rec = tracker.record_call(model="x", input_tokens=1, output_tokens=1, agent="a")
    assert rec.cost_usd == 1.23
    assert sink.received == [rec]


def test_record_call_invokes_gate_commit() -> None:
    sink = _Capturing()
    gate = BudgetGate([BudgetRule(name="g", limit_usd=10.0)])
    tracker = UsageTracker(sinks=[sink], resolver=lambda ctx: 0.5, gate=gate)
    tracker.record_call(model="x", input_tokens=1, output_tokens=1,
                        scope_ctx=ScopeContext(tenant="acme"))
    assert gate.spend("g") == pytest.approx(0.5)


def test_record_call_propagates_budget_exception() -> None:
    from fireflyframework_agentic.exceptions import BudgetExceededError
    sink = _Capturing()
    gate = BudgetGate([BudgetRule(name="g", limit_usd=0.1)])
    tracker = UsageTracker(sinks=[sink], resolver=lambda ctx: 1.0, gate=gate)
    with pytest.raises(BudgetExceededError):
        tracker.record_call(model="x", input_tokens=1, output_tokens=1)


def test_record_legacy_path_still_works() -> None:
    sink = _Capturing()
    tracker = UsageTracker(sinks=[sink], resolver=None, gate=None)
    tracker.record(UsageRecord(agent="a", cost_usd=0.01))
    assert sink.received[0].cost_usd == 0.01


def test_add_sink_appends_to_chain() -> None:
    s1 = _Capturing()
    s2 = _Capturing()
    tracker = UsageTracker(sinks=[s1], resolver=None, gate=None)
    tracker.add_sink(s2)
    tracker.record(UsageRecord(cost_usd=0.0))
    assert len(s1.received) == 1
    assert len(s2.received) == 1
```

- [ ] **Step 3: Run, expect failures (new signature does not exist yet)**

```bash
pytest tests/unit/observability/test_usage.py -v
```

- [ ] **Step 4: Rewrite `usage.py`**

Replace `fireflyframework_agentic/observability/usage.py` with the following. Keep `UsageRecord` and `UsageSummary` shapes byte-for-byte identical:

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""Usage tracking for LLM API calls.

:class:`UsageTracker` is a thin orchestrator: it resolves cost via a
``CostResolver`` chain, builds a :class:`UsageRecord`, hands the record
to a :class:`BudgetGate` for accumulation/enforcement, then fans the
record out to a chain of :class:`CostSink` consumers.

The legacy ``record(usage)`` low-level entry is preserved for in-tree
producers that already construct a :class:`UsageRecord` (agents,
reasoning, experiments).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.observability.budget import BudgetGate, ScopeContext
from fireflyframework_agentic.observability.cost.resolvers import (
    CostContext,
    CostFn,
    resolve_cost,
)
from fireflyframework_agentic.observability.cost.tiers import CallTier
from fireflyframework_agentic.observability.sinks import CostSink, _emit_safely

logger = logging.getLogger(__name__)


class UsageRecord(BaseModel):
    """A single LLM usage observation. Schema is intentionally stable."""

    agent: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    request_count: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""


class UsageSummary(BaseModel):
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_requests: int = 0
    total_latency_ms: float = 0.0
    record_count: int = 0
    by_agent: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_model: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _aggregate(records: list[UsageRecord]) -> UsageSummary:
    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                 "cost_usd": 0.0, "requests": 0}
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                 "cost_usd": 0.0, "requests": 0}
    )
    total_in = total_out = total_tok = total_req = 0
    total_cost = total_lat = 0.0
    for r in records:
        total_in += r.input_tokens
        total_out += r.output_tokens
        total_tok += r.total_tokens
        total_req += r.request_count
        total_cost += r.cost_usd
        total_lat += r.latency_ms
        if r.agent:
            a = by_agent[r.agent]
            a["input_tokens"] += r.input_tokens
            a["output_tokens"] += r.output_tokens
            a["total_tokens"] += r.total_tokens
            a["cost_usd"] += r.cost_usd
            a["requests"] += r.request_count
        if r.model:
            m = by_model[r.model]
            m["input_tokens"] += r.input_tokens
            m["output_tokens"] += r.output_tokens
            m["total_tokens"] += r.total_tokens
            m["cost_usd"] += r.cost_usd
            m["requests"] += r.request_count
    return UsageSummary(
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_tokens=total_tok,
        total_cost_usd=total_cost,
        total_requests=total_req,
        total_latency_ms=total_lat,
        record_count=len(records),
        by_agent=dict(by_agent),
        by_model=dict(by_model),
    )


# Type alias: a resolver is either the full chain (Sequence[CostFn]) or a single callable.
_ResolverArg = Sequence[CostFn] | Callable[[CostContext], float] | None


class UsageTracker:
    """Thread-safe accumulator + fan-out for :class:`UsageRecord`."""

    def __init__(
        self,
        *,
        sinks: Sequence[CostSink] | None = None,
        resolver: _ResolverArg = None,
        gate: BudgetGate | None = None,
        max_records: int = 0,
    ) -> None:
        self._records: list[UsageRecord] = []
        self._cumulative_cost: float = 0.0
        self._max_records = max_records
        self._lock = threading.Lock()
        self._sinks: list[CostSink] = list(sinks or [])
        self._resolver = resolver
        self._gate = gate

    # -- High-level entry ------------------------------------------------
    def record_call(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        reasoning_tokens: int = 0,
        tier: CallTier = CallTier.STANDARD,
        provider_payload: Mapping[str, Any] | None = None,
        agent: str = "",
        correlation_id: str = "",
        latency_ms: float = 0.0,
        request_count: int = 0,
        scope_ctx: ScopeContext | None = None,
    ) -> UsageRecord:
        ctx = CostContext(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            reasoning_tokens=reasoning_tokens,
            tier=tier,
            provider_payload=provider_payload,
        )
        cost = self._resolve(ctx)
        record = UsageRecord(
            agent=agent,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens + reasoning_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            request_count=request_count,
            cost_usd=cost,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
        )
        self.record(record, scope_ctx=scope_ctx)
        return record

    def _resolve(self, ctx: CostContext) -> float:
        if self._resolver is None:
            return resolve_cost(ctx)
        if callable(self._resolver):
            result = self._resolver(ctx)
            return 0.0 if result is None else float(result)
        return resolve_cost(ctx, self._resolver)

    # -- Low-level entry -------------------------------------------------
    def record(self, usage: UsageRecord, scope_ctx: ScopeContext | None = None) -> None:
        with self._lock:
            self._records.append(usage)
            self._cumulative_cost += usage.cost_usd
            if self._max_records > 0 and len(self._records) > self._max_records:
                excess = len(self._records) - self._max_records
                del self._records[:excess]
        if self._gate is not None:
            self._gate.commit(usage, scope_ctx or ScopeContext())
        for sink in self._sinks:
            _emit_safely(sink, usage)

    # -- Sink management -------------------------------------------------
    def add_sink(self, sink: CostSink) -> None:
        self._sinks.append(sink)

    # -- Read accessors --------------------------------------------------
    @property
    def records(self) -> list[UsageRecord]:
        with self._lock:
            return list(self._records)

    @property
    def cumulative_cost_usd(self) -> float:
        with self._lock:
            return self._cumulative_cost

    def get_summary(self) -> UsageSummary:
        with self._lock:
            return _aggregate(list(self._records))

    def get_summary_for_agent(self, agent_name: str) -> UsageSummary:
        with self._lock:
            filtered = [r for r in self._records if r.agent == agent_name]
        return _aggregate(filtered)

    def get_summary_for_correlation(self, correlation_id: str) -> UsageSummary:
        with self._lock:
            filtered = [r for r in self._records if r.correlation_id == correlation_id]
        return _aggregate(filtered)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._cumulative_cost = 0.0


def _build_default_tracker() -> UsageTracker:
    """Construct the module-level tracker with defaults driven by config."""
    from fireflyframework_agentic.observability.sinks import EventBusSink, OTelMetricsSink

    sinks: list[CostSink] = [OTelMetricsSink(), EventBusSink()]
    gate: BudgetGate | None = None
    max_records = 10_000
    try:
        from fireflyframework_agentic.config import get_config
        from fireflyframework_agentic.observability.budget import BudgetRule

        cfg = get_config()
        if cfg.budget_limit_usd is not None:
            gate = BudgetGate([BudgetRule(name="config_global", limit_usd=cfg.budget_limit_usd)])
        max_records = cfg.usage_tracker_max_records
    except Exception:  # noqa: BLE001
        logger.debug("Falling back to defaults for usage tracker", exc_info=True)
    return UsageTracker(sinks=sinks, gate=gate, max_records=max_records)


default_usage_tracker = _build_default_tracker()
```

- [ ] **Step 5: Run new tests + the legacy test_usage.py — expect green**

```bash
pytest tests/unit/observability/test_usage.py -v
```

If any legacy tests fail because they relied on the singleton's auto-emit-to-metrics path: the new default tracker still attaches `OTelMetricsSink + EventBusSink` so the same `default_metrics`/`default_events` calls happen.

- [ ] **Step 6: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/observability/usage.py tests/unit/observability/test_usage.py
git -C /home/u/signature/fireflyframework-agentic commit -m "refactor(observability): rewire UsageTracker around resolver/gate/sinks"
```

---

## Phase 7 — Migrate production call sites

### Task 7.1: Migrate `agents/base.py`

**Files:**
- Modify: `fireflyframework_agentic/agents/base.py:425-463` (the `_record_usage` block)

- [ ] **Step 1: Read the existing block to confirm exact line range**

```bash
sed -n '420,465p' fireflyframework_agentic/agents/base.py
```

- [ ] **Step 2: Replace the `get_cost_calculator` + manual record build with `record_call`**

In `fireflyframework_agentic/agents/base.py`, find the block (around line 444-461) that reads:

```python
            model_name = self._model_identifier
            calculator = get_cost_calculator(cfg.cost_calculator)
            cost = calculator.estimate(model_name, input_tokens, output_tokens)

            record = UsageRecord(
                agent=self._name,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cache_creation_tokens=cache_creation,
                cache_read_tokens=cache_read,
                request_count=request_count,
                cost_usd=cost,
                latency_ms=elapsed_ms,
                correlation_id=correlation_id,
            )
            default_usage_tracker.record(record)
```

Replace with:

```python
            default_usage_tracker.record_call(
                model=self._model_identifier,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation,
                cache_read_tokens=cache_read,
                request_count=request_count,
                agent=self._name,
                correlation_id=correlation_id,
                latency_ms=elapsed_ms,
                scope_ctx=ScopeContext(agent=self._name, model=self._model_identifier,
                                       correlation_id=correlation_id),
            )
```

Add the import at the top of the file:

```python
from fireflyframework_agentic.observability.budget import ScopeContext
```

Remove the now-unused imports (`from fireflyframework_agentic.observability.cost import get_cost_calculator` if present — the module will be deleted in Phase 8).

- [ ] **Step 3: Run agents tests, expect green**

```bash
pytest tests/unit/agents/ -q
```

- [ ] **Step 4: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/agents/base.py
git -C /home/u/signature/fireflyframework-agentic commit -m "refactor(agents): use UsageTracker.record_call instead of manual cost calc"
```

### Task 7.2: Migrate `reasoning/base.py:511`

**Files:**
- Modify: `fireflyframework_agentic/reasoning/base.py` around line 511

- [ ] **Step 1: Read the block**

```bash
sed -n '480,520p' fireflyframework_agentic/reasoning/base.py
```

- [ ] **Step 2: Apply the same shape of refactor as Task 7.1**

Replace the `calculator = get_cost_calculator(...)` + `record = UsageRecord(...)` + `default_usage_tracker.record(record)` block with a single `default_usage_tracker.record_call(...)` call that passes the same fields. Add the `from fireflyframework_agentic.observability.budget import ScopeContext` import.

- [ ] **Step 3: Run reasoning tests**

```bash
pytest tests/unit/reasoning/ -q
```

- [ ] **Step 4: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/reasoning/base.py
git -C /home/u/signature/fireflyframework-agentic commit -m "refactor(reasoning): use UsageTracker.record_call"
```

### Task 7.3: Migrate `experiments/runner.py:98`

**Files:**
- Modify: `fireflyframework_agentic/experiments/runner.py:90-110`

- [ ] **Step 1: Read the block**

```bash
sed -n '85,110p' fireflyframework_agentic/experiments/runner.py
```

- [ ] **Step 2: This call site already has a fully-built `UsageRecord` (`variant_result`). It is the canonical user of low-level `record(usage)`. Leave it as-is.**

No change needed. The low-level path is the right entry here.

- [ ] **Step 3: Skip commit (no change)**

### Task 7.4: Migrate `CostGuardMiddleware`

**Files:**
- Modify: `fireflyframework_agentic/agents/builtin_middleware.py:223-300`
- Modify: `tests/unit/agents/test_middleware.py` (or wherever `CostGuard` is tested)

- [ ] **Step 1: Replace the implementation; keep the constructor signature**

Replace lines 223-300 of `fireflyframework_agentic/agents/builtin_middleware.py` (the `class CostGuardMiddleware` block) with:

```python
class CostGuardMiddleware:
    """Enforces a cumulative cost budget before each agent run.

    Backed internally by :class:`~fireflyframework_agentic.observability.budget.BudgetGate`.
    The public constructor signature is unchanged.

    Parameters:
        budget_usd: Maximum cumulative spend in USD.
        tracker: A :class:`UsageTracker` whose ``cumulative_cost_usd`` is consulted.
            Defaults to the module-level ``default_usage_tracker``.
        warn_only: When *True*, log a warning instead of raising.
        per_call_limit_usd: Optional per-call spending cap.
    """

    def __init__(
        self,
        budget_usd: float,
        *,
        tracker: Any | None = None,
        warn_only: bool = False,
        per_call_limit_usd: float | None = None,
    ) -> None:
        from fireflyframework_agentic.observability.budget import (
            BudgetGate, BudgetMode, BudgetRule,
        )

        self._budget = budget_usd
        self._tracker = tracker
        self._warn_only = warn_only
        self._per_call_limit = per_call_limit_usd
        mode = BudgetMode.SOFT if warn_only else BudgetMode.HARD
        self._gate = BudgetGate(
            [BudgetRule(name="costguard", limit_usd=budget_usd, mode=mode)]
        )

    def _get_tracker(self) -> Any:
        if self._tracker is not None:
            return self._tracker
        from fireflyframework_agentic.observability.usage import default_usage_tracker
        return default_usage_tracker

    async def before_run(self, context: MiddlewareContext) -> None:
        from fireflyframework_agentic.observability.budget import ScopeContext

        tracker = self._get_tracker()
        current = tracker.cumulative_cost_usd
        context.metadata["_cost_before"] = current
        # Seed the gate's lifetime accumulator with the tracker's current spend
        # so it raises consistently with the legacy semantics.
        self._gate.reset()
        self._gate.commit(
            UsageRecord(cost_usd=current),
            ScopeContext(agent=context.agent_name),
        )

    async def after_run(self, context: MiddlewareContext, result: Any) -> Any:
        if self._per_call_limit is None:
            return result
        cost_before = context.metadata.get("_cost_before", 0.0)
        cost_after = self._get_tracker().cumulative_cost_usd
        call_cost = cost_after - cost_before
        if call_cost > self._per_call_limit:
            msg = (
                f"Per-call cost limit exceeded for agent '{context.agent_name}': "
                f"${call_cost:.4f} > ${self._per_call_limit:.4f}"
            )
            if self._warn_only:
                logger.warning("CostGuardMiddleware (warn-only): %s", msg)
            else:
                raise BudgetExceededError(
                    msg,
                    rule_name="costguard.per_call",
                    spend_usd=call_cost,
                    limit_usd=self._per_call_limit,
                )
        return result
```

Add `from fireflyframework_agentic.observability.usage import UsageRecord` at the top of `builtin_middleware.py` if it is not already imported.

- [ ] **Step 2: Run the existing middleware tests**

```bash
pytest tests/unit/agents/test_middleware.py -v
```

Fix any test that constructs `BudgetExceededError(msg)` and expects no fields — the new `__init__` accepts a positional `msg` with default `""` so existing tests still work.

- [ ] **Step 3: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add fireflyframework_agentic/agents/builtin_middleware.py
git -C /home/u/signature/fireflyframework-agentic commit -m "refactor(middleware): back CostGuardMiddleware with BudgetGate"
```

---

## Phase 8 — Deletions & config cleanup

### Task 8.1: Delete `observability/cost.py` and stale exports

**Files:**
- Delete: `fireflyframework_agentic/observability/cost.py` (the old file — note the new `cost/` package takes its place)
- Delete: `tests/unit/observability/test_cost.py`
- Modify: `fireflyframework_agentic/observability/__init__.py`
- Modify: `fireflyframework_agentic/observability/quota.py` (drop budget code; consume `bucket_key`)
- Modify: `fireflyframework_agentic/config.py` (remove fields)

- [ ] **Step 1: Confirm no remaining importers of the old API**

```bash
grep -rn "get_cost_calculator\|StaticPriceCostCalculator\|GenAIPricesCostCalculator\|CostCalculator" fireflyframework_agentic/ tests/ examples/ 2>/dev/null | grep -v __pycache__
```

If anything other than the file we are about to delete shows up, fix the importer first.

- [ ] **Step 2: Delete the old module and its test**

```bash
git -C /home/u/signature/fireflyframework-agentic rm fireflyframework_agentic/observability/cost.py
git -C /home/u/signature/fireflyframework-agentic rm tests/unit/observability/test_cost.py
```

Then verify the new `cost/` directory imports cleanly:

```bash
python -c "from fireflyframework_agentic.observability.cost import resolve_cost, CallTier; print('ok')"
```

- [ ] **Step 3: Update `observability/__init__.py`**

Replace the cost-related imports and `__all__` entries:

```python
# Replace this block:
from fireflyframework_agentic.observability.cost import (
    CostCalculator,
    GenAIPricesCostCalculator,
    StaticPriceCostCalculator,
    get_cost_calculator,
)
# ... with:
from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
)
from fireflyframework_agentic.observability.cost import (
    CallTier,
    CostContext,
    DEFAULT_RESOLVERS,
    genai_prices_cost,
    provider_reported_cost,
    resolve_cost,
)
from fireflyframework_agentic.observability.sinks import (
    CostSink,
    EventBusSink,
    JSONLFileSink,
    LoggingSink,
    OTelMetricsSink,
    WebhookSink,
)
```

Update `__all__` to remove `CostCalculator`, `GenAIPricesCostCalculator`, `StaticPriceCostCalculator`, `get_cost_calculator` and add the new names. Keep alphabetical.

- [ ] **Step 4: Strip budget logic out of `quota.py`**

Open `fireflyframework_agentic/observability/quota.py`. Find the `QuotaManager` budget-related members (`daily_budget_usd`, `check_budget_available`, daily-spend tracking). Remove them. Keep `RateLimiter` and any rate-limiter-only state on `QuotaManager`.

If `RateLimiter` does any window math, replace its inline logic with a call to `bucket_key("daily", datetime.now(UTC))` from `_windows.py` so the two consumers share the helper.

```bash
pytest tests/unit/observability/test_quota_manager.py -v
```

Update any test asserting the deleted budget APIs to test rate limiting only.

- [ ] **Step 5: Remove deprecated config fields**

In `fireflyframework_agentic/config.py` (line 110, 113):

Delete:
```python
    budget_alert_threshold_usd: float | None = None
    """Soft alert threshold in USD.  A warning is logged when reached."""

    cost_calculator: Literal["auto", "genai_prices", "static"] = "auto"
    """Cost calculator preference: ``"auto"``, ``"genai_prices"``, or ``"static"``."""
```

Then, in the same file, add a validator that raises `ConfigError` if either of these fields is present in the input dict (so users get a migration pointer instead of a silent ignore):

Find the existing model validator section (search for `@model_validator`) and add:

```python
    @model_validator(mode="before")
    @classmethod
    def _reject_removed_cost_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            removed = {"cost_calculator", "budget_alert_threshold_usd"} & set(data)
            if removed:
                raise ValueError(
                    f"Removed cost-tracking config fields: {sorted(removed)}. "
                    "See docs/observability.md for the new BudgetGate / resolver API."
                )
        return data
```

Update any existing config validator that references `budget_alert_threshold_usd` (lines ~261-267 in the spec context) — delete the cross-field check entirely.

- [ ] **Step 6: Run the full test suite**

```bash
pytest tests/unit/ -q
```

Expected: all green. Fix any test that imports a removed symbol.

- [ ] **Step 7: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add -A
git -C /home/u/signature/fireflyframework-agentic commit -m "refactor(observability): delete legacy cost.py, prune config, share bucket_key"
```

### Task 8.2: Promote `genai-prices` to core dep

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add to `[project.dependencies]`**

In `pyproject.toml` lines 30-37, add `"genai-prices>=0.0.1",` to the core `dependencies = [...]` list.

- [ ] **Step 2: Remove the `[costs]` extra (line 80-81)**

Delete:
```toml
costs = [
    "genai-prices>=0.0.1",
]
```

Also remove the `costs` token from the `all = [...]` aggregate around line 135.

- [ ] **Step 3: Reinstall and verify**

```bash
pip install -e .
python -c "from genai_prices import find_model; print('ok')"
```

- [ ] **Step 4: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add pyproject.toml
git -C /home/u/signature/fireflyframework-agentic commit -m "build: promote genai-prices to core dependency"
```

---

## Phase 9 — Example

### Task 9.1: Write `examples/cost_tracking.py`

**Files:**
- Create: `examples/cost_tracking.py`

- [ ] **Step 1: Author the example**

```python
# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0

"""End-to-end cost tracking example.

Demonstrates:

* A custom :class:`CostFn` (``fixed_rate_cost``) inserted in front of the
  default resolver chain — useful for contractually-fixed-price models.
* A :class:`BudgetGate` with two rules: a tenant-scoped HARD daily limit
  and an agent-scoped SOFT lifetime limit.
* A custom JSONL sink running alongside the default :class:`OTelMetricsSink`
  and :class:`EventBusSink`.
* One synthetic record that exercises cache tokens and ``CallTier.BATCH``
  so every axis lights up.
"""

from __future__ import annotations

import json
from pathlib import Path

from fireflyframework_agentic.observability.budget import (
    BudgetGate,
    BudgetMode,
    BudgetRule,
    BudgetWindow,
    ScopeContext,
)
from fireflyframework_agentic.observability.cost import (
    CallTier,
    CostContext,
    DEFAULT_RESOLVERS,
)
from fireflyframework_agentic.observability.sinks import (
    EventBusSink,
    JSONLFileSink,
    OTelMetricsSink,
)
from fireflyframework_agentic.observability.usage import UsageRecord, UsageTracker

_FIXED_PRICES = {"acme:internal-llm": (0.5e-6, 2.0e-6)}  # (input, output) per token.


def fixed_rate_cost(ctx: CostContext) -> float | None:
    """Return the negotiated USD cost for contractually-priced models."""
    price = _FIXED_PRICES.get(ctx.model)
    if price is None:
        return None
    input_price, output_price = price
    return ctx.input_tokens * input_price + ctx.output_tokens * output_price


def build_tracker(jsonl_path: Path) -> UsageTracker:
    gate = BudgetGate(
        [
            BudgetRule(
                name="acme-daily",
                limit_usd=5.0,
                mode=BudgetMode.HARD,
                window=BudgetWindow.DAILY,
                match={"tenant": "acme"},
            ),
            BudgetRule(
                name="writer-lifetime",
                limit_usd=100.0,
                mode=BudgetMode.SOFT,
                window=BudgetWindow.LIFETIME,
                match={"agent": "writer"},
            ),
        ]
    )
    sinks = [OTelMetricsSink(), EventBusSink(), JSONLFileSink(jsonl_path)]
    resolvers = [fixed_rate_cost, *DEFAULT_RESOLVERS]
    return UsageTracker(sinks=sinks, gate=gate, resolver=resolvers)


def main() -> None:
    out = Path("/tmp/firefly-cost.jsonl")
    out.unlink(missing_ok=True)
    tracker = build_tracker(out)

    tracker.record_call(
        model="anthropic:claude-3-5-sonnet-latest",
        input_tokens=1_000,
        output_tokens=500,
        cache_creation_tokens=2_000,
        cache_read_tokens=8_000,
        tier=CallTier.BATCH,
        agent="writer",
        correlation_id="demo-run-1",
        scope_ctx=ScopeContext(
            tenant="acme",
            agent="writer",
            correlation_id="demo-run-1",
            labels={"env": "prod"},
        ),
    )

    line = out.read_text(encoding="utf-8").splitlines()[0]
    rec = json.loads(line)
    print(f"emitted record cost_usd=${rec['cost_usd']:.6f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it as a smoke test**

```bash
python examples/cost_tracking.py
```

Expected: prints a non-zero `cost_usd` line, no exceptions.

- [ ] **Step 3: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add examples/cost_tracking.py
git -C /home/u/signature/fireflyframework-agentic commit -m "docs(examples): end-to-end cost tracking walkthrough"
```

---

## Phase 10 — Docs and changelog

### Task 10.1: Rewrite the "Cost Calculation" section of `docs/observability.md`

**Files:**
- Modify: `docs/observability.md` (the "Cost Calculation" section, around lines 236-290)

- [ ] **Step 1: Replace the section**

Replace the current "Cost Calculation" section heading and body with three new sections: **Cost Resolution**, **Budgets**, **Cost Sinks**. Each section should be ~15-25 lines with a runnable code snippet drawn from `examples/cost_tracking.py`.

Concrete content:

```markdown
## Cost Resolution

Each LLM call is priced by a chain of resolver callables. The default chain tries the provider-reported cost first (e.g. OpenRouter's `usage.cost`), then falls back to `genai-prices` for token-by-token computation. Cache tokens, reasoning tokens, and the `BATCH` tier are all honored when the provider's price record exposes the relevant fields.

```python
from fireflyframework_agentic.observability.cost import resolve_cost, CostContext, CallTier
cost = resolve_cost(CostContext(model="anthropic:claude-3-5-sonnet-latest",
                                input_tokens=1_000, output_tokens=500,
                                cache_read_tokens=8_000, tier=CallTier.BATCH))
```

Custom strategies plug in by passing your own chain: `resolve_cost(ctx, [my_fixed_rate, *DEFAULT_RESOLVERS])`. See `examples/cost_tracking.py`.

When `genai-prices` has no entry for a model, the resolver returns `0.0`, increments the `cost_unknown` metric, and logs a WARNING once per model.

## Budgets

A `BudgetGate` holds a sequence of `BudgetRule` objects. Each rule filters via a `match` dict (AND of key-value pairs against the call's `ScopeContext`), has a window (`LIFETIME`, `MONTHLY`, `DAILY`), and a mode (`HARD` raises `BudgetExceededError`; `SOFT` logs).

```python
from fireflyframework_agentic.observability.budget import (
    BudgetGate, BudgetMode, BudgetRule, BudgetWindow, ScopeContext,
)
gate = BudgetGate([
    BudgetRule(name="acme-daily", limit_usd=5.0, window=BudgetWindow.DAILY,
               match={"tenant": "acme"}),
    BudgetRule(name="writer-lifetime", limit_usd=100.0, mode=BudgetMode.SOFT,
               match={"agent": "writer"}),
])
```

For the single-tenant case, the `budget_limit_usd` config field auto-installs a global HARD rule on the default tracker.

## Cost Sinks

`UsageTracker` fans every `UsageRecord` out to one or more `CostSink` instances. Built-ins: `OTelMetricsSink`, `EventBusSink`, `LoggingSink`, `JSONLFileSink`, `WebhookSink`. Custom sinks implement the protocol's `emit(record)` method.

```python
from fireflyframework_agentic.observability.sinks import (
    EventBusSink, JSONLFileSink, OTelMetricsSink,
)
from fireflyframework_agentic.observability.usage import UsageTracker
tracker = UsageTracker(sinks=[OTelMetricsSink(), EventBusSink(),
                              JSONLFileSink("/var/log/firefly/cost.jsonl")])
```

A failing sink does not break other sinks; failures increment `cost_sink_errors` labeled by sink class.
```

- [ ] **Step 2: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add docs/observability.md
git -C /home/u/signature/fireflyframework-agentic commit -m "docs(observability): document new cost resolver / budget / sink API"
```

### Task 10.2: Update `CHANGELOG.md`

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a `## [Unreleased]` block at the top**

```markdown
## [Unreleased]

### Changed (BREAKING)
- Cost tracking redesigned around `resolve_cost` chain, `BudgetGate`, and pluggable `CostSink`s. See `docs/observability.md` for the new API and `examples/cost_tracking.py` for a walkthrough.
- `genai-prices` promoted from optional `[costs]` extra to a required dependency. The static price table and the `cost_calculator` config field are removed.
- The `budget_alert_threshold_usd` config field is removed (paired with the simpler rule-based budget model). Setting it raises `ConfigError`.

### Removed
- `StaticPriceCostCalculator`, `GenAIPricesCostCalculator`, `CostCalculator`, `get_cost_calculator` (replaced by `resolve_cost` + `CostFn` callables).
- `QuotaManager.daily_budget_usd` and `QuotaManager.check_budget_available` (use a `BudgetRule(window=DAILY)`).

### Added
- `fireflyframework_agentic.observability.cost.resolve_cost` and `CostContext`.
- `fireflyframework_agentic.observability.budget.{BudgetGate,BudgetRule,ScopeContext,BudgetMode,BudgetWindow}`.
- `fireflyframework_agentic.observability.sinks.{CostSink,OTelMetricsSink,EventBusSink,LoggingSink,JSONLFileSink,WebhookSink}`.
- `fireflyframework_agentic.observability._windows.bucket_key` (internal, shared by BudgetGate and RateLimiter).
- New `UsageTracker.record_call(...)` high-level entry that resolves cost and delegates to `record(usage)`.
```

- [ ] **Step 2: Commit**

```bash
git -C /home/u/signature/fireflyframework-agentic add CHANGELOG.md
git -C /home/u/signature/fireflyframework-agentic commit -m "docs(changelog): record cost-tracking redesign"
```

---

## Phase 11 — Final verification

### Task 11.1: Full test suite + example

**Files:** none

- [ ] **Step 1: Run all unit tests**

```bash
pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 2: Run the new example as a smoke test**

```bash
python examples/cost_tracking.py
```

Expected: prints a `cost_usd=$0.xxxxxx` line.

- [ ] **Step 3: Run mypy / pyright on the new modules** (if the repo uses one)

```bash
test -f mypy.ini -o -f pyproject.toml && grep -q "mypy\|pyright" pyproject.toml && mypy fireflyframework_agentic/observability/ || echo "no static checker configured"
```

Fix any type errors surfaced before claiming done.

- [ ] **Step 4: Verify no orphan imports**

```bash
grep -rn "get_cost_calculator\|StaticPriceCostCalculator\|GenAIPricesCostCalculator" fireflyframework_agentic/ tests/ examples/ 2>/dev/null | grep -v __pycache__
```

Expected: empty output.

- [ ] **Step 5: Open PR**

```bash
git -C /home/u/signature/fireflyframework-agentic push -u origin cost-tracking-redesign
gh pr create --repo fireflyframework/fireflyframework-agentic --title "feat(observability): cost tracking redesign" --body "$(cat <<'EOF'
## Summary
- Replace static price table with `genai-prices`-backed resolver chain (`provider_reported_cost`, `genai_prices_cost`).
- Introduce `BudgetGate` with scoped, windowed rules (LIFETIME / MONTHLY / DAILY; HARD or SOFT).
- Introduce `CostSink` protocol and ship five built-ins (OTelMetrics, EventBus, Logging, JSONLFile, Webhook).
- Slim `UsageTracker` into a thin orchestrator; `record_call(...)` is the new high-level entry.
- Promote `genai-prices` to a core dependency; remove `cost_calculator` and `budget_alert_threshold_usd` config.

## Test plan
- [ ] `pytest tests/unit/observability -q`
- [ ] `pytest tests/unit/agents tests/unit/reasoning -q`
- [ ] `python examples/cost_tracking.py` runs and prints a cost line
EOF
)"
```

---

## Self-Review

Run after writing the plan; this is a check against the spec.

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| §3 Architecture (file layout) | Tasks 1.1, 2.1–2.5, 4.1–4.4, 5.1–5.4, 6.1, 8.1 |
| §4.1 CostResolver (provider_reported_cost, genai_prices_cost, resolve_cost, DEFAULT_RESOLVERS, CallTier) | Tasks 2.1, 2.3, 2.4, 2.5 |
| §4.2 BudgetGate (scope match dict, three windows, hard/soft, BudgetExceededError extended) | Tasks 3.1, 4.1, 4.2, 4.3, 4.4 |
| §4.3 Sinks (CostSink protocol, 5 built-ins, error isolation) | Tasks 5.1, 5.2, 5.3, 5.4 |
| §4.4 UsageTracker (record + record_call, schema unchanged, sink chain) | Task 6.1 |
| §5 Example | Task 9.1 |
| §6 Configuration (remove cost_calculator + budget_alert_threshold_usd; keep budget_limit_usd) | Task 8.1 step 5 |
| §7 Error handling (unknown model, sink isolation, BudgetExceededError) | Tasks 2.4, 5.1, 3.1 |
| §8 Testing strategy | Tasks 1.1, 2.x, 4.x, 5.x, 6.1; plus regression sweep in 11.1 |
| §9 Migration & rollout | Phases 7, 8, 10, 11 |
| §11 Revision-history items (match dict, list[CostFn], three windows, bucket_key shared, alert_at removed, exception extended in place, WebhookSink in core, ScopeContext separate, record kept) | All present across the named phases |

No gaps.

**Placeholder scan:** No "TBD", "TODO", "implement later", or "similar to Task N". All code is inlined.

**Type / name consistency:**
- `bucket_key(window: str, moment: datetime)` (Task 1.1) is called from `BudgetGate` (Task 4.3) with `rule.window.value` (the enum's str value) and `datetime.now(UTC)`. Consistent.
- `CostFn = Callable[[CostContext], float | None]` (Task 2.2) — `provider_reported_cost`, `genai_prices_cost`, and `fixed_rate_cost` all match this signature.
- `BudgetRule.match: Mapping[str, str]` (Task 4.2) — every test and the example use plain dicts. Consistent.
- `BudgetExceededError(msg, *, rule_name, spend_usd, limit_usd)` (Task 3.1) — every raise site uses these kwargs (Tasks 4.3, 7.4). Consistent.
- `UsageTracker.record_call(*, model, input_tokens, output_tokens, ..., scope_ctx)` (Task 6.1) — call sites in Tasks 7.1, 7.2 pass exactly these kwargs.
- `UsageRecord` schema (Task 6.1) — unchanged byte-for-byte from today. Confirmed against `fireflyframework_agentic/observability/usage.py` source.

Plan complete and saved to `docs/superpowers/plans/2026-05-12-cost-tracking-redesign.md`.
