"""Tests for noted.display."""

from datetime import UTC, datetime

from noted.display import display_count, display_notes_table
from noted.models import Note, NoteSummary


def test_display_notes_table_renders() -> None:
    """Test that notes table renders without error."""
    notes = [
        Note(
            id=1,
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
