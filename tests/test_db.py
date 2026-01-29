"""Tests for noted.db."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from noted.db import (
    _cache_is_fresh,
    _source_db_path,
    apple_timestamp_to_datetime,
    clear_cache,
    get_connection,
    get_note_content,
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


def test_get_connection(tmp_path: Path) -> None:
    """Test getting a read-only database connection."""
    # Create a minimal SQLite database for testing
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("CREATE TABLE test (id INTEGER)")
    conn.close()

    with patch("noted.db.ensure_cached_db", return_value=test_db):
        conn = get_connection()
        assert conn is not None
        # Verify it's read-only by trying to write
        try:
            conn.execute("INSERT INTO test VALUES (1)")
            conn.commit()
            assert False, "Should have raised error for read-only"
        except sqlite3.OperationalError as e:
            assert "readonly" in str(e).lower()
        conn.close()


def test_get_note_content(tmp_path: Path) -> None:
    """Test fetching raw note content bytes."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)

    # Create minimal schema matching Apple Notes
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE1 TEXT,
            ZMARKEDFORDELETION INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)

    # Insert test note
    conn.execute("INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE1) VALUES (1, 'Test')")
    test_data = b"\x1f\x8b\x08\x00test"  # Fake gzip-like data
    conn.execute("INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (1, 1, ?)", (test_data,))
    conn.commit()
    conn.close()

    # Reopen read-only
    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = get_note_content(conn, 1)
    assert result == test_data
    conn.close()


def test_get_note_content_not_found(tmp_path: Path) -> None:
    """Test fetching content for non-existent note."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE1 TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = get_note_content(conn, 999)
    assert result is None
    conn.close()
