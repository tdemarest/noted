"""Tests for noted.models."""

from datetime import datetime

from noted.models import Note, NoteSummary


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
