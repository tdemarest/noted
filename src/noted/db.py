"""Database operations for Apple Notes.

Handles copying, caching, and querying the Notes SQLite database.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

# Apple Notes database location
NOTES_DIR = Path.home() / "Library/Group Containers/group.com.apple.notes"

# Cache location for copied database
CACHE_DIR = Path.home() / ".cache/noted"

# Files that make up the SQLite database
DB_FILES = ["NoteStore.sqlite", "NoteStore.sqlite-shm", "NoteStore.sqlite-wal"]

# Apple Core Data epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def apple_timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert Apple Core Data timestamp to datetime.

    Apple timestamps are seconds since 2001-01-01 00:00:00 UTC.

    Args:
        timestamp: Apple timestamp in seconds, or None.

    Returns:
        datetime in UTC, or None if input was None.
    """
    if timestamp is None:
        return None
    return APPLE_EPOCH + timedelta(seconds=timestamp)
