"""Tests for noted.cli."""

import gzip
from datetime import UTC, datetime
from pathlib import Path
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
            identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
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


def test_view_command_success() -> None:
    """Test view command with valid note."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
    ):
        result = runner.invoke(app, ["view", "42"])

    assert result.exit_code == 0
    assert "Test Note" in result.output
    assert "Hello, world!" in result.output


def test_view_command_not_found() -> None:
    """Test view command with non-existent note."""
    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=None),
    ):
        result = runner.invoke(app, ["view", "999"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_view_command_locked() -> None:
    """Test view command with locked note."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Secret Note",
        folder=None,
        created=None,
        modified=None,
    )
    # Non-gzip data indicates locked
    locked_data = b"\x00\x01\x02\x03"

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=locked_data),
    ):
        result = runner.invoke(app, ["view", "42"])

    assert result.exit_code == 1
    assert "locked" in result.output.lower()


def test_view_zip_without_attachments() -> None:
    """Test that --zip without --attachments shows error."""
    result = runner.invoke(app, ["view", "42", "--zip"])
    assert result.exit_code == 1
    assert "requires" in result.output.lower() or "attachments" in result.output.lower()


def test_view_attachments_flag_exports(tmp_path: Path) -> None:
    """Test --attachments flag triggers export."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf with no attachments
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.Path.cwd", return_value=tmp_path),
    ):
        result = runner.invoke(app, ["view", "42", "--attachments"])

    assert result.exit_code == 0
    # Should create note file in tmp_path
    note_files = list(tmp_path.glob("*.md")) + list(tmp_path.glob("*.txt"))
    assert len(note_files) >= 1 or "Exported" in result.output


def test_debug_option_shows_uuid() -> None:
    """Test --debug option shows note UUID in output."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.db.get_attachment_stats", return_value={"count": 0, "total_size": 0}),
    ):
        result = runner.invoke(app, ["--debug", "view", "42"])

    assert result.exit_code == 0
    # Debug output should include the UUID
    assert "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE" in result.output


def test_debug_short_option() -> None:
    """Test -d short option works same as --debug."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.db.get_attachment_stats", return_value={"count": 0, "total_size": 0}),
    ):
        result = runner.invoke(app, ["-d", "view", "42"])

    assert result.exit_code == 0
    # Debug output should include the UUID
    assert "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE" in result.output


def test_debug_shows_row_id() -> None:
    """Test --debug option shows row ID."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.db.get_attachment_stats", return_value={"count": 0, "total_size": 0}),
    ):
        result = runner.invoke(app, ["--debug", "view", "42"])

    assert result.exit_code == 0
    # Debug should show the row ID
    assert "42" in result.output or "Row ID" in result.output


def test_debug_off_hides_uuid() -> None:
    """Test that UUID is not shown without --debug."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
    ):
        result = runner.invoke(app, ["view", "42"])

    assert result.exit_code == 0
    # Without debug, UUID should NOT be shown in output
    assert "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE" not in result.output


def test_debug_shows_attachment_count() -> None:
    """Test --debug shows attachment count."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    # Mock attachment stats
    mock_stats = {"count": 3, "total_size": 1024 * 500}  # 500 KB

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.db.get_attachment_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["--debug", "view", "42"])

    assert result.exit_code == 0
    # Should show attachment count
    assert "3" in result.output
    assert "Attachment" in result.output


def test_debug_shows_attachment_size() -> None:
    """Test --debug shows total attachment size."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    # Mock attachment stats: 2.5 MB
    mock_stats = {"count": 5, "total_size": 1024 * 1024 * 2.5}

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.db.get_attachment_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["--debug", "view", "42"])

    assert result.exit_code == 0
    # Should show size (formatted as MB or similar)
    assert "MB" in result.output or "KB" in result.output or "2.5" in result.output


def test_debug_zero_attachments() -> None:
    """Test --debug handles notes with no attachments."""
    mock_note = Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    # No attachments
    mock_stats = {"count": 0, "total_size": 0}

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.db.get_attachment_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["--debug", "view", "42"])

    assert result.exit_code == 0
    # Should still show attachment info, even if 0
    assert "Attachment" in result.output
