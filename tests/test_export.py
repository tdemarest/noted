"""Tests for noted.export module."""

import gzip
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from noted.models import Note


def test_export_options_defaults() -> None:
    """Test ExportOptions has sensible defaults."""
    from noted.export import ExportOptions

    opts = ExportOptions(output_dir=Path("./export"))
    assert opts.output_dir == Path("./export")
    assert opts.include_deleted is True
    assert opts.create_archive is False
    assert opts.folder_filter is None
    assert opts.verbose is False


def test_note_export_result_success() -> None:
    """Test NoteExportResult for successful export."""
    from noted.export import NoteExportResult

    result = NoteExportResult(
        note_id=42,
        identifier="uuid-123",
        title="Test Note",
        folder="Work",
        status="success",
        path=Path("Work/Test_Note/Test_Note.md"),
        attachment_count=3,
        error=None,
    )
    assert result.status == "success"
    assert result.error is None
    assert result.attachment_count == 3


def test_note_export_result_locked() -> None:
    """Test NoteExportResult for locked note."""
    from noted.export import NoteExportResult

    result = NoteExportResult(
        note_id=55,
        identifier="uuid-456",
        title="Secret",
        folder="Personal",
        status="locked",
        path=Path("Personal/Secret/Secret.md"),
        attachment_count=0,
        error=None,
    )
    assert result.status == "locked"


def test_export_error() -> None:
    """Test ExportError contains error details."""
    from noted.export import ExportError

    error = ExportError(
        note_id=99,
        identifier="uuid-789",
        title="Broken Note",
        folder="Work",
        error="Failed to decompress",
    )
    assert error.note_id == 99
    assert error.error == "Failed to decompress"


def test_full_export_result() -> None:
    """Test FullExportResult aggregates statistics."""
    from noted.export import FullExportResult

    result = FullExportResult(
        output_dir=Path("./notes_export"),
        archive_path=None,
        total_notes=100,
        exported_count=97,
        locked_count=2,
        failed_count=1,
        total_attachments=50,
        folders=["Work", "Personal"],
        notes=[],
        errors=[],
    )
    assert result.total_notes == 100
    assert result.exported_count == 97
    assert result.locked_count == 2
    assert result.failed_count == 1


def test_generate_locked_placeholder() -> None:
    """Test locked note placeholder content."""
    from noted.export import generate_locked_placeholder

    note = Note(
        id=55,
        identifier="LOCKED-UUID-123",
        title="Secret Note",
        folder="Personal",
        created=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        modified=datetime(2026, 1, 20, 14, 30, tzinfo=UTC),
    )

    content = generate_locked_placeholder(note)

    assert "# Secret Note" in content
    assert "locked" in content.lower()
    assert "LOCKED-UUID-123" in content
    assert "Personal" in content


def test_generate_locked_placeholder_no_folder() -> None:
    """Test locked placeholder for note without folder."""
    from noted.export import generate_locked_placeholder

    note = Note(
        id=55,
        identifier="LOCKED-UUID-123",
        title="Secret Note",
        folder=None,
        created=None,
        modified=None,
    )

    content = generate_locked_placeholder(note)

    assert "(No Folder)" in content


def test_make_unique_folder_name_no_conflict() -> None:
    """Test folder name generation without conflicts."""
    from noted.export import make_unique_folder_name

    used: set[str] = set()
    result = make_unique_folder_name("Meeting_Notes", "uuid-123", used)
    assert result == "Meeting_Notes"
    assert "Meeting_Notes" in used


def test_make_unique_folder_name_with_conflict() -> None:
    """Test folder name adds UUID suffix on conflict."""
    from noted.export import make_unique_folder_name

    used = {"Meeting_Notes"}
    result = make_unique_folder_name("Meeting_Notes", "abc123def456", used)
    assert result == "Meeting_Notes_abc123"
    assert "Meeting_Notes_abc123" in used


def test_generate_master_index(tmp_path: Path) -> None:
    """Test master index.json generation."""
    from noted.export import (
        ExportError,
        FullExportResult,
        NoteExportResult,
        generate_master_index,
    )

    result = FullExportResult(
        output_dir=tmp_path,
        archive_path=None,
        total_notes=3,
        exported_count=2,
        locked_count=1,
        failed_count=0,
        total_attachments=5,
        folders=["Work", "Personal"],
        notes=[
            NoteExportResult(
                note_id=1,
                identifier="uuid-1",
                title="Note 1",
                folder="Work",
                status="success",
                path=Path("Work/Note_1/Note_1.md"),
                attachment_count=3,
                error=None,
            ),
            NoteExportResult(
                note_id=2,
                identifier="uuid-2",
                title="Locked",
                folder="Personal",
                status="locked",
                path=Path("Personal/Locked/Locked.md"),
                attachment_count=0,
                error=None,
            ),
        ],
        errors=[
            ExportError(
                note_id=99,
                identifier="uuid-99",
                title="Broken",
                folder="Work",
                error="Decompression failed",
            ),
        ],
    )

    folder_info = [
        {"name": "Work", "path": "Work/", "note_count": 1},
        {"name": "Personal", "path": "Personal/", "note_count": 1},
    ]

    index_path = tmp_path / "index.json"
    generate_master_index(index_path, result, folder_info)

    assert index_path.exists()
    data = json.loads(index_path.read_text())

    assert data["export_version"] == "1.0"
    assert data["source"] == "Apple Notes"
    assert data["statistics"]["total_notes"] == 3
    assert data["statistics"]["exported_count"] == 2
    assert data["statistics"]["locked_count"] == 1
    assert data["statistics"]["total_folders"] == 2
    assert len(data["folders"]) == 2
    assert len(data["notes"]) == 2
    assert len(data["errors"]) == 1

    # Check first note
    note1 = data["notes"][0]
    assert note1["id"] == 1
    assert note1["identifier"] == "uuid-1"
    assert note1["export_status"] == "success"

    # Check error
    error1 = data["errors"][0]
    assert error1["note_id"] == 99
    assert error1["error"] == "Decompression failed"


def test_export_single_note(tmp_path: Path) -> None:
    """Test exporting a single note to folder structure."""
    from noted.export import export_single_note

    # Create minimal test database
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZTITLE1 TEXT,
            ZTITLE2 TEXT,
            ZFOLDER INTEGER,
            ZMEDIA INTEGER,
            ZFILENAME TEXT,
            ZMERGEABLEDATA1 BLOB,
            ZSUMMARY TEXT,
            ZNOTE INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)

    # Build minimal gzipped protobuf for "Hello, World!"
    # Structure: root -> document -> note -> text
    note_proto = b"\x12\x0dHello, World!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    # Insert note record (required for the JOIN in get_note_content)
    conn.execute(
        """INSERT INTO ZICCLOUDSYNCINGOBJECT
           (Z_PK, ZIDENTIFIER, ZTITLE1)
           VALUES (?, ?, ?)""",
        (1, "test-uuid-123", "Test Note"),
    )
    # Insert note data
    conn.execute(
        "INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (?, ?, ?)",
        (1, 1, compressed),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    note = Note(
        id=1,
        identifier="test-uuid-123",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    output_dir = tmp_path / "export"
    result = export_single_note(conn, note, output_dir)

    conn.close()

    assert result.status == "success"
    assert result.path is not None
    assert result.error is None

    # Check file was created
    note_file = output_dir / result.path
    assert note_file.exists()
    content = note_file.read_text()
    assert "Test Note" in content
    assert "Hello" in content


def test_export_single_note_no_content(tmp_path: Path) -> None:
    """Test exporting a note with no content returns failed status."""
    from noted.export import export_single_note

    # Create database without note data
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT
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

    note = Note(
        id=999,
        identifier="nonexistent",
        title="Missing Note",
        folder="Work",
        created=None,
        modified=None,
    )

    output_dir = tmp_path / "export"
    result = export_single_note(conn, note, output_dir)

    conn.close()

    assert result.status == "failed"
    assert result.error is not None
    assert "no content" in result.error.lower()
