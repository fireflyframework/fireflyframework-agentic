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
