"""Tests for noted.display."""

from datetime import UTC, datetime
from unittest.mock import patch

from noted.display import (
    _format_file_size,
    display_count,
    display_note_view,
    display_notes_table,
    display_warning,
    table_to_markdown,
    table_to_rich,
)
from noted.models import Note, NoteContent, NoteSummary, Table


def test_display_notes_table_renders() -> None:
    """Test that notes table renders without error."""
    notes = [
        Note(
            id=1,
            identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
            title="Test Note",
            folder="Personal",
            created=datetime(2025, 1, 15, 10, 30, tzinfo=UTC),
            modified=datetime(2025, 1, 28, 14, 45, tzinfo=UTC),
        ),
    ]
    # Should not raise
    display_notes_table(notes)


def test_display_notes_table_empty() -> None:
    """Test displaying empty notes list."""
    # Should not raise
    display_notes_table([])


def test_display_count_total() -> None:
    """Test displaying total count."""
    summary = NoteSummary(total_count=42, folder_counts={})
    # Should not raise
    display_count(summary)


def test_display_count_by_folder() -> None:
    """Test displaying counts by folder."""
    summary = NoteSummary(
        total_count=42,
        folder_counts={"Personal": 20, "Work": 22},
    )
    # Should not raise
    display_count(summary)


def test_display_note_view() -> None:
    """Test displaying a note with content."""
    note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=datetime(2025, 1, 15, 10, 30, tzinfo=UTC),
        modified=datetime(2025, 1, 28, 14, 45, tzinfo=UTC),
    )
    content = NoteContent(text="This is the note body.\nWith multiple lines.")

    # Should not raise
    display_note_view(note, content)


def test_display_note_view_no_folder() -> None:
    """Test displaying a note without a folder."""
    note = Note(
        id=1,
        identifier="BBBBBBBB-CCCC-DDDD-EEEE-FFFFFFFFFFFF",
        title="Orphan Note",
        folder=None,
        created=datetime(2025, 1, 1, tzinfo=UTC),
        modified=datetime(2025, 1, 1, tzinfo=UTC),
    )
    content = NoteContent(text="Content here")

    # Should not raise
    display_note_view(note, content)


def test_table_to_rich() -> None:
    """Test converting Table to Rich Table."""
    table = Table(
        rows=2,
        columns=2,
        cells={(0, 0): "A", (0, 1): "B", (1, 0): "C", (1, 1): "D"},
    )
    rich_table = table_to_rich(table)
    # Rich Table should have 2 columns
    assert len(rich_table.columns) == 2


def test_table_to_rich_empty_cells() -> None:
    """Test Rich table with missing cells shows empty."""
    table = Table(rows=2, columns=2, cells={(0, 0): "Only"})
    rich_table = table_to_rich(table)
    assert len(rich_table.columns) == 2


def test_table_to_markdown() -> None:
    """Test converting Table to markdown string."""
    table = Table(
        rows=2,
        columns=2,
        cells={(0, 0): "A", (0, 1): "B", (1, 0): "C", (1, 1): "D"},
    )
    md = table_to_markdown(table)
    assert "| A | B |" in md
    assert "| C | D |" in md
    assert "---" in md  # Header separator


def test_display_warning() -> None:
    """Test warning message display."""
    with patch("noted.display.console") as mock_console:
        display_warning("Skipped 2 attachments")
        mock_console.print.assert_called_once()
        call_arg = mock_console.print.call_args[0][0]
        assert "Warning" in call_arg or "warning" in call_arg.lower()
        assert "Skipped 2 attachments" in call_arg


def test_format_file_size_bytes() -> None:
    """Test file size formatting for bytes."""
    assert _format_file_size(0) == "0 B"
    assert _format_file_size(512) == "512 B"
    assert _format_file_size(1023) == "1023 B"


def test_format_file_size_kilobytes() -> None:
    """Test file size formatting for kilobytes."""
    assert _format_file_size(1024) == "1.0 KB"
    assert _format_file_size(1536) == "1.5 KB"
    assert _format_file_size(1024 * 500) == "500.0 KB"


def test_format_file_size_megabytes() -> None:
    """Test file size formatting for megabytes."""
    assert _format_file_size(1024 * 1024) == "1.0 MB"
    assert _format_file_size(1024 * 1024 * 2.5) == "2.5 MB"
    assert _format_file_size(1024 * 1024 * 100) == "100.0 MB"


def test_format_file_size_gigabytes() -> None:
    """Test file size formatting for gigabytes."""
    assert _format_file_size(1024 * 1024 * 1024) == "1.0 GB"
    assert _format_file_size(1024 * 1024 * 1024 * 3.5) == "3.5 GB"
