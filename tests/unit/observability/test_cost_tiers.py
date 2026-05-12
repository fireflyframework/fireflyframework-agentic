from fireflyframework_agentic.observability.cost.tiers import CallTier


def test_call_tier_values() -> None:
    assert CallTier.STANDARD == "standard"
    assert CallTier.BATCH == "batch"


def test_call_tier_is_str() -> None:
    assert isinstance(CallTier.BATCH, str)
