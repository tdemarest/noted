"""Tests for noted.models."""

from datetime import datetime

from noted.models import Attachment, Note, NoteContent, NoteSummary, Table


def test_note_creation() -> None:
    """Test Note dataclass creation."""
    note = Note(
        id=1,
        title="Test Note",
        folder="Personal",
        created=datetime(2025, 1, 15, 10, 30),
        modified=datetime(2025, 1, 28, 14, 45),
    )
    assert note.id == 1
    assert note.title == "Test Note"
    assert note.folder == "Personal"
    assert note.created == datetime(2025, 1, 15, 10, 30)
    assert note.modified == datetime(2025, 1, 28, 14, 45)


def test_note_with_none_folder() -> None:
    """Test Note with no folder."""
    note = Note(
        id=2,
        title="Orphan Note",
        folder=None,
        created=datetime(2025, 1, 1),
        modified=datetime(2025, 1, 1),
    )
    assert note.folder is None


def test_note_summary_creation() -> None:
    """Test NoteSummary dataclass creation."""
    summary = NoteSummary(
        total_count=42,
        folder_counts={"Personal": 20, "Work": 22},
    )
    assert summary.total_count == 42
    assert summary.folder_counts["Personal"] == 20
    assert summary.folder_counts["Work"] == 22


def test_note_summary_empty_folders() -> None:
    """Test NoteSummary with no folders."""
    summary = NoteSummary(total_count=0, folder_counts={})
    assert summary.total_count == 0
    assert summary.folder_counts == {}


def test_note_content_creation() -> None:
    """Test NoteContent dataclass creation."""
    content = NoteContent(text="Hello, world!")
    assert content.text == "Hello, world!"


def test_note_content_empty() -> None:
    """Test NoteContent with empty text."""
    content = NoteContent(text="")
    assert content.text == ""


def test_table_creation() -> None:
    """Test Table dataclass creation."""
    cells = {(0, 0): "A", (0, 1): "B", (1, 0): "C", (1, 1): "D"}
    table = Table(rows=2, columns=2, cells=cells)
    assert table.rows == 2
    assert table.columns == 2
    assert table.get_cell(0, 0) == "A"
    assert table.get_cell(1, 1) == "D"


def test_table_get_cell_missing() -> None:
    """Test Table.get_cell returns empty string for missing cells."""
    table = Table(rows=2, columns=2, cells={(0, 0): "A"})
    assert table.get_cell(0, 0) == "A"
    assert table.get_cell(1, 1) == ""


def test_attachment_with_table() -> None:
    """Test Attachment can hold a Table."""
    table = Table(rows=1, columns=1, cells={(0, 0): "X"})
    attachment = Attachment(
        identifier="uuid-123",
        type_uti="com.apple.notes.table",
        title=None,
        table=table,
    )
    assert attachment.table is not None
    assert attachment.table.get_cell(0, 0) == "X"
