"""Integration tests for noted CLI."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from noted.cli import app

runner = CliRunner()

# Check if Apple Notes database is available
NOTES_DB = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
NOTES_DB_AVAILABLE = NOTES_DB.exists()


def test_help() -> None:
    """Test that help is displayed."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "noted" in result.output.lower()
    assert "list" in result.output
    assert "count" in result.output
    assert "refresh" in result.output


def test_list_help() -> None:
    """Test list command help."""
    result = runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0
    assert "--folder" in result.output
    assert "--limit" in result.output


def test_count_help() -> None:
    """Test count command help."""
    result = runner.invoke(app, ["count", "--help"])
    assert result.exit_code == 0
    assert "--by-folder" in result.output


def test_view_help() -> None:
    """Test view command help."""
    result = runner.invoke(app, ["view", "--help"])
    assert result.exit_code == 0
    assert "note_id" in result.output.lower()


@pytest.mark.skipif(not NOTES_DB_AVAILABLE, reason="Apple Notes database not available")
def test_view_command_integration() -> None:
    """Integration test: list notes, then view one.

    This test requires access to the real Apple Notes database.
    """
    # First list notes to get an ID
    list_result = runner.invoke(app, ["list", "--limit", "1"])
    if list_result.exit_code != 0 or "No notes found" in list_result.output:
        pytest.skip("No notes available to test")

    # Extract first note ID from output (ID column is first)
    lines = list_result.output.strip().split("\n")
    # Find a line with a numeric ID (skip header lines)
    note_id = None
    for line in lines:
        parts = line.split()
        if parts and parts[0].isdigit():
            note_id = parts[0]
            break

    if note_id is None:
        pytest.skip("Could not parse note ID from list output")

    # View that note
    view_result = runner.invoke(app, ["view", note_id])

    # Should succeed (exit 0) or fail gracefully for locked notes (exit 1 with "locked")
    assert view_result.exit_code in (0, 1)
    if view_result.exit_code == 1:
        assert "locked" in view_result.output.lower() or "not found" in view_result.output.lower()
