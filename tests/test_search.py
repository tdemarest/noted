"""Tests for noted.search module."""

import gzip
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from noted import search
from noted.models import Note, SearchResult


@pytest.fixture
def mock_cache_dir(tmp_path: Path) -> Path:
    """Create a temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def mock_notes_db(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Create a mock notes database with test data."""
    db_path = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create minimal schema matching Apple Notes
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTITLE1 TEXT,
            ZTITLE2 TEXT,
            ZFOLDER INTEGER,
            ZPARENT INTEGER,
            ZCREATIONDATE REAL,
            ZMODIFICATIONDATE REAL,
            ZMARKEDFORDELETION INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)

    # Create test folder
    conn.execute("""
        INSERT INTO ZICCLOUDSYNCINGOBJECT
        (Z_PK, ZIDENTIFIER, ZTITLE2, ZPARENT)
        VALUES (100, 'folder-1', 'Test Folder', NULL)
    """)

    # Create test notes with gzip-compressed protobuf content
    # Minimal valid protobuf structure for a note
    def create_note_content(text: str) -> bytes:
        """Create minimal gzip-compressed note content."""
        # This is a simplified protobuf structure
        # Field 2 (Document) > Field 3 (Note) > Field 2 (note_text)
        text_bytes = text.encode("utf-8")
        note_text_field = b"\x12" + bytes([len(text_bytes)]) + text_bytes
        note_field = b"\x1a" + bytes([len(note_text_field)]) + note_text_field
        doc_field = b"\x12" + bytes([len(note_field)]) + note_field
        return gzip.compress(doc_field)

    # Note 1: Regular note
    conn.execute("""
        INSERT INTO ZICCLOUDSYNCINGOBJECT
        (Z_PK, ZIDENTIFIER, ZTITLE1, ZFOLDER, ZCREATIONDATE, ZMODIFICATIONDATE, ZMARKEDFORDELETION)
        VALUES (1, 'note-uuid-1', 'Meeting Notes', 100, 758629800.0, 758629800.0, 0)
    """)
    content1 = create_note_content("Discuss budget and Q2 projections for the project.")
    conn.execute("INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (1, 1, ?)", (content1,))

    # Note 2: Another regular note
    conn.execute("""
        INSERT INTO ZICCLOUDSYNCINGOBJECT
        (Z_PK, ZIDENTIFIER, ZTITLE1, ZFOLDER, ZCREATIONDATE, ZMODIFICATIONDATE, ZMARKEDFORDELETION)
        VALUES (2, 'note-uuid-2', 'Shopping List', 100, 758629900.0, 758629900.0, 0)
    """)
    content2 = create_note_content("Buy milk, eggs, and bread. Check project deadline.")
    conn.execute("INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (2, 2, ?)", (content2,))

    # Note 3: Locked note (no gzip magic bytes)
    conn.execute("""
        INSERT INTO ZICCLOUDSYNCINGOBJECT
        (Z_PK, ZIDENTIFIER, ZTITLE1, ZFOLDER, ZCREATIONDATE, ZMODIFICATIONDATE, ZMARKEDFORDELETION)
        VALUES (3, 'note-uuid-3', 'Secret Note', 100, 758630000.0, 758630000.0, 0)
    """)
    conn.execute(
        "INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (3, 3, ?)",
        (b"\x00\x00encrypted_data",),
    )

    conn.commit()
    return conn, db_path


def test_index_exists_false(mock_cache_dir: Path) -> None:
    """Test _index_exists returns False when no index."""
    with patch.object(search, "FTS_INDEX_PATH", mock_cache_dir / "fts_index.sqlite"):
        assert search._index_exists() is False


def test_index_exists_true(mock_cache_dir: Path) -> None:
    """Test _index_exists returns True when index file exists."""
    index_path = mock_cache_dir / "fts_index.sqlite"
    index_path.write_text("fake")

    with patch.object(search, "FTS_INDEX_PATH", index_path):
        assert search._index_exists() is True


def test_clear_index(mock_cache_dir: Path) -> None:
    """Test clear_index removes the index file."""
    index_path = mock_cache_dir / "fts_index.sqlite"
    index_path.write_text("fake index data")

    with patch.object(search, "FTS_INDEX_PATH", index_path):
        assert index_path.exists()
        search.clear_index()
        assert not index_path.exists()


def test_clear_index_no_file(mock_cache_dir: Path) -> None:
    """Test clear_index when file doesn't exist."""
    index_path = mock_cache_dir / "fts_index.sqlite"

    with patch.object(search, "FTS_INDEX_PATH", index_path):
        # Should not raise
        search.clear_index()


def test_build_index(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test building the FTS index."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        count = search.build_index(notes_conn, show_progress=False)

        # Should index 2 notes (note 3 is locked)
        assert count == 2
        assert index_path.exists()

        # Verify index contents
        fts_conn = sqlite3.connect(index_path)
        fts_conn.row_factory = sqlite3.Row

        # Check notes_fts table
        cursor = fts_conn.execute("SELECT COUNT(*) FROM notes_fts")
        assert cursor.fetchone()[0] == 2

        # Check metadata
        cursor = fts_conn.execute("SELECT value FROM fts_metadata WHERE key = 'note_count'")
        assert cursor.fetchone()["value"] == "2"

        fts_conn.close()


def test_search_notes_basic(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test basic content search."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        # Build index first
        search.build_index(notes_conn, show_progress=False)

        # Search for "budget"
        results = search.search_notes(notes_conn, "budget")

        assert len(results) == 1
        assert results[0].note.title == "Meeting Notes"
        assert "budget" in results[0].snippet.lower()


def test_search_notes_multiple_results(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test search returning multiple results."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        search.build_index(notes_conn, show_progress=False)

        # Search for "project" - appears in both notes
        results = search.search_notes(notes_conn, "project")

        assert len(results) == 2


def test_search_notes_no_results(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test search with no matching results."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        search.build_index(notes_conn, show_progress=False)

        results = search.search_notes(notes_conn, "nonexistent_term")

        assert len(results) == 0


def test_search_notes_with_limit(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test search with result limit."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        search.build_index(notes_conn, show_progress=False)

        # Search for "project" with limit 1
        results = search.search_notes(notes_conn, "project", limit=1)

        assert len(results) == 1


def test_skip_locked_notes(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test that locked notes are skipped during indexing."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        count = search.build_index(notes_conn, show_progress=False)

        # Note 3 is locked, should be skipped
        assert count == 2

        # Verify locked note is not in index
        fts_conn = sqlite3.connect(index_path)
        cursor = fts_conn.execute("SELECT * FROM notes_fts WHERE title = 'Secret Note'")
        assert cursor.fetchone() is None
        fts_conn.close()


def test_index_freshness(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test index freshness detection."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
    ):
        # Initially stale (no index)
        with patch.object(search, "_cached_db_mtime", return_value=1000.0):
            assert search._index_is_fresh() is False

        # Build index with mtime 1000
        with patch.object(search, "_cached_db_mtime", return_value=1000.0):
            search.build_index(notes_conn, show_progress=False)
            assert search._index_is_fresh() is True

        # Cached db updated (mtime increased)
        with patch.object(search, "_cached_db_mtime", return_value=2000.0):
            assert search._index_is_fresh() is False


def test_get_index_status_no_index(mock_cache_dir: Path) -> None:
    """Test get_index_status when no index exists."""
    index_path = mock_cache_dir / "fts_index.sqlite"

    with patch.object(search, "FTS_INDEX_PATH", index_path):
        status = search.get_index_status()

        assert status["exists"] is False
        assert status["fresh"] is False


def test_get_index_status_with_index(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test get_index_status with existing index."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        search.build_index(notes_conn, show_progress=False)

        status = search.get_index_status()

        assert status["exists"] is True
        assert status["fresh"] is True
        assert status["note_count"] == 2
        assert "built_at" in status
        assert "size_bytes" in status


def test_search_invalid_fts_syntax(
    mock_notes_db: tuple[sqlite3.Connection, Path],
    mock_cache_dir: Path,
) -> None:
    """Test that invalid FTS5 syntax returns empty results."""
    notes_conn, db_path = mock_notes_db
    index_path = mock_cache_dir / "fts_index.sqlite"

    with (
        patch.object(search, "FTS_INDEX_PATH", index_path),
        patch.object(search.db, "CACHE_DIR", mock_cache_dir),
        patch.object(search, "_cached_db_mtime", return_value=1000.0),
    ):
        search.build_index(notes_conn, show_progress=False)

        # Invalid FTS5 syntax (unmatched quote)
        results = search.search_notes(notes_conn, '"unclosed quote')

        assert len(results) == 0
