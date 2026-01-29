"""Tests for noted.export module."""

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
