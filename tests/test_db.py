"""Tests for noted.db."""

from datetime import UTC, datetime

from noted.db import apple_timestamp_to_datetime


def test_apple_timestamp_to_datetime() -> None:
    """Test conversion of Apple Core Data timestamp to datetime.

    Apple timestamps are seconds since 2001-01-01 00:00:00 UTC.
    """
    # 2025-01-15 10:30:00 UTC
    # Seconds from 2001-01-01 to 2025-01-15 10:30:00
    apple_ts = 758629800.0
    result = apple_timestamp_to_datetime(apple_ts)
    expected = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
    assert result == expected


def test_apple_timestamp_none() -> None:
    """Test that None timestamp returns None."""
    result = apple_timestamp_to_datetime(None)
    assert result is None
