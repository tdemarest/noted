"""Tests for noted.cli."""

from datetime import UTC, datetime
from unittest.mock import patch

from typer.testing import CliRunner

from noted.cli import app
from noted.models import Note, NoteSummary

runner = CliRunner()


def test_list_command() -> None:
    """Test the list command."""
    mock_notes = [
        Note(
            id=1,
            title="Test Note",
            folder="Personal",
            created=datetime(2025, 1, 15, tzinfo=UTC),
            modified=datetime(2025, 1, 28, tzinfo=UTC),
        ),
    ]

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.list_notes", return_value=mock_notes),
    ):
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "Test Note" in result.output


def test_count_command() -> None:
    """Test the count command."""
    mock_summary = NoteSummary(total_count=42, folder_counts={})

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_summary", return_value=mock_summary),
    ):
        result = runner.invoke(app, ["count"])
        assert result.exit_code == 0
        assert "42" in result.output


def test_count_by_folder() -> None:
    """Test the count --by-folder command."""
    mock_summary = NoteSummary(
        total_count=42,
        folder_counts={"Personal": 20, "Work": 22},
    )

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_summary", return_value=mock_summary),
    ):
        result = runner.invoke(app, ["count", "--by-folder"])
        assert result.exit_code == 0
        assert "Personal" in result.output
        assert "Work" in result.output


def test_refresh_command() -> None:
    """Test the refresh command."""
    with patch("noted.cli.db.clear_cache") as mock_clear:
        result = runner.invoke(app, ["refresh"])
        assert result.exit_code == 0
        mock_clear.assert_called_once()
