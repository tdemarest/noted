"""Database operations for Apple Notes.

Handles copying, caching, and querying the Notes SQLite database.
"""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger

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


def _source_db_path() -> Path:
    """Get path to the source Notes database.

    Returns:
        Path to NoteStore.sqlite in Apple Notes directory.
    """
    return NOTES_DIR / "NoteStore.sqlite"


def _source_mtime() -> float:
    """Get modification time of source database.

    Returns:
        Modification time as Unix timestamp.

    Raises:
        FileNotFoundError: If source database doesn't exist.
    """
    return _source_db_path().stat().st_mtime


def _cache_is_fresh() -> bool:
    """Check if cached copy exists and is newer than source.

    Returns:
        True if cache exists and is at least as new as source.
    """
    cached = CACHE_DIR / "NoteStore.sqlite"
    if not cached.exists():
        return False
    try:
        return cached.stat().st_mtime >= _source_mtime()
    except FileNotFoundError:
        return False


def ensure_cached_db() -> Path:
    """Ensure database is cached, copying if stale or missing.

    Copies all SQLite files (db, wal, shm) to cache directory.
    Only copies if source is newer than cache.

    Returns:
        Path to cached NoteStore.sqlite.

    Raises:
        FileNotFoundError: If source database doesn't exist.
    """
    if not _cache_is_fresh():
        logger.info("Cache stale or missing, copying database...")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for filename in DB_FILES:
            src = NOTES_DIR / filename
            if src.exists():
                shutil.copy2(src, CACHE_DIR / filename)
                logger.debug(f"Copied {filename}")
        logger.info(f"Database cached to {CACHE_DIR}")
    else:
        logger.debug("Using cached database")
    return CACHE_DIR / "NoteStore.sqlite"


def clear_cache() -> None:
    """Delete cached database files to force refresh on next access."""
    if not CACHE_DIR.exists():
        return
    for filename in DB_FILES:
        cached = CACHE_DIR / filename
        if cached.exists():
            cached.unlink()
            logger.debug(f"Deleted {filename}")
    logger.info("Cache cleared")
