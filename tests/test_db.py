"""Tests for noted.db."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from noted.db import (
    _cache_is_fresh,
    _source_db_path,
    apple_timestamp_to_datetime,
    clear_cache,
)


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


def test_source_db_path() -> None:
    """Test that source DB path is correct."""
    path = _source_db_path()
    assert path.name == "NoteStore.sqlite"
    assert "group.com.apple.notes" in str(path)


def test_cache_is_fresh_no_cache(tmp_path: Path) -> None:
    """Test cache freshness when no cache exists."""
    with patch("noted.db.CACHE_DIR", tmp_path):
        assert _cache_is_fresh() is False


def test_clear_cache(tmp_path: Path) -> None:
    """Test clearing the cache directory."""
    with patch("noted.db.CACHE_DIR", tmp_path):
        # Create fake cached files
        (tmp_path / "NoteStore.sqlite").write_text("fake")
        (tmp_path / "NoteStore.sqlite-wal").write_text("fake")

        clear_cache()

        assert not (tmp_path / "NoteStore.sqlite").exists()
        assert not (tmp_path / "NoteStore.sqlite-wal").exists()


def test_clear_cache_no_dir(tmp_path: Path) -> None:
    """Test clearing cache when directory doesn't exist."""
    nonexistent = tmp_path / "nonexistent"
    with patch("noted.db.CACHE_DIR", nonexistent):
        # Should not raise
        clear_cache()
