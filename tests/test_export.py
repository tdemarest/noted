"""Tests for noted.export module."""

from pathlib import Path


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
