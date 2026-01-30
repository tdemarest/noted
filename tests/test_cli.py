"""Tests for noted.cli."""

import gzip
from datetime import UTC, datetime
from unittest.mock import patch

from typer.testing import CliRunner

from noted.cli import app
from noted.models import DatabaseStats, Note

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


def test_stats_command() -> None:
    """Test the stats command."""
    mock_stats = DatabaseStats(
        total_notes=42,
        pinned_notes=5,
        locked_notes=2,
        deleted_notes=1,
        notes_with_checklists=10,
        notes_with_incomplete_checklists=3,
        folder_counts={},
        total_attachments=100,
        attachment_type_counts={"public.jpeg": 50, "com.adobe.pdf": 30},
        attachments_with_location=5,
        database_size_bytes=1024 * 1024 * 50,  # 50 MB
        cache_modified=None,
        fts_index_size_bytes=1024 * 100,
        fts_index_built_at="2025-01-29T12:00:00",
        fts_index_fresh=True,
        fts_indexed_notes=42,
    )

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_database_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "42" in result.output
        assert "Total" in result.output


def test_stats_by_folder() -> None:
    """Test the stats --by-folder command."""
    mock_stats = DatabaseStats(
        total_notes=42,
        pinned_notes=5,
        locked_notes=2,
        deleted_notes=1,
        notes_with_checklists=10,
        notes_with_incomplete_checklists=3,
        folder_counts={"Personal": 20, "Work": 22},
        total_attachments=100,
        attachment_type_counts={"public.jpeg": 50},
        attachments_with_location=5,
        database_size_bytes=1024 * 1024 * 50,
        cache_modified=None,
        fts_index_size_bytes=1024 * 100,
        fts_index_built_at="2025-01-29T12:00:00",
        fts_index_fresh=True,
        fts_indexed_notes=42,
    )

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_database_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["stats", "--by-folder"])
        assert result.exit_code == 0
        assert "Personal" in result.output
        assert "Work" in result.output


def test_stats_shows_pinned() -> None:
    """Test stats command shows pinned notes count."""
    mock_stats = DatabaseStats(
        total_notes=100,
        pinned_notes=15,
        locked_notes=0,
        deleted_notes=0,
        notes_with_checklists=0,
        notes_with_incomplete_checklists=0,
        folder_counts={},
        total_attachments=0,
        attachment_type_counts={},
        attachments_with_location=0,
        database_size_bytes=1024 * 1024 * 10,
        cache_modified=None,
        fts_index_size_bytes=1024 * 100,
        fts_index_built_at="2025-01-29T12:00:00",
        fts_index_fresh=True,
        fts_indexed_notes=100,
    )

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_database_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "Pinned" in result.output
        assert "15" in result.output


def test_stats_shows_attachments() -> None:
    """Test stats command shows attachment statistics."""
    mock_stats = DatabaseStats(
        total_notes=50,
        pinned_notes=0,
        locked_notes=0,
        deleted_notes=0,
        notes_with_checklists=0,
        notes_with_incomplete_checklists=0,
        folder_counts={},
        total_attachments=200,
        attachment_type_counts={
            "public.jpeg": 80,
            "public.png": 40,
            "com.adobe.pdf": 50,
            "com.apple.notes.table": 30,
        },
        attachments_with_location=10,
        database_size_bytes=1024 * 1024 * 25,
        cache_modified=None,
        fts_index_size_bytes=1024 * 100,
        fts_index_built_at="2025-01-29T12:00:00",
        fts_index_fresh=True,
        fts_indexed_notes=50,
    )

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_database_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "Attachments" in result.output
        assert "200" in result.output


def test_stats_json_output() -> None:
    """Test stats command with JSON output."""
    mock_stats = DatabaseStats(
        total_notes=42,
        pinned_notes=5,
        locked_notes=2,
        deleted_notes=1,
        notes_with_checklists=10,
        notes_with_incomplete_checklists=3,
        folder_counts={},
        total_attachments=100,
        attachment_type_counts={"public.jpeg": 50},
        attachments_with_location=5,
        database_size_bytes=1024 * 1024 * 50,
        cache_modified=None,
        fts_index_size_bytes=1024 * 100,
        fts_index_built_at="2025-01-29T12:00:00",
        fts_index_fresh=True,
        fts_indexed_notes=42,
    )

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_database_stats", return_value=mock_stats),
    ):
        result = runner.invoke(app, ["stats", "--json"])
        assert result.exit_code == 0
        # Should be valid JSON
        import json
        data = json.loads(result.output)
        assert data["notes"]["total"] == 42
        assert data["notes"]["pinned"] == 5
        assert data["attachments"]["total"] == 100
        assert data["cache"]["database_size_bytes"] == 1024 * 1024 * 50
        assert data["cache"]["fts_index_fresh"] is True


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


def test_export_command_help() -> None:
    """Test export command has help text."""
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "Export notes" in result.output or "export" in result.output.lower()
    assert "--all" in result.output


def test_export_requires_all_or_note_id() -> None:
    """Test export requires either --all or note_id."""
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 1
    assert "either" in result.output.lower() or "specify" in result.output.lower()


def test_export_all_not_with_note_id() -> None:
    """Test export --all cannot be used with a note_id."""
    result = runner.invoke(app, ["export", "42", "--all"])
    assert result.exit_code == 1
    assert "cannot" in result.output.lower()
