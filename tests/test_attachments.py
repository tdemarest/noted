"""Tests for noted.attachments."""

import json
from pathlib import Path

from noted.attachments import (
    AttachmentExportResult,
    ExportedAttachment,
    generate_manifest,
    get_skip_reason,
    make_unique_filename,
    sanitize_filename,
    uti_to_extension,
)


def test_exported_attachment_exported() -> None:
    """Test ExportedAttachment for successfully exported file."""
    att = ExportedAttachment(
        identifier="uuid-123",
        filename="photo.jpg",
        type_uti="public.jpeg",
        exported=True,
        skip_reason=None,
    )
    assert att.identifier == "uuid-123"
    assert att.filename == "photo.jpg"
    assert att.exported is True
    assert att.skip_reason is None


def test_exported_attachment_skipped() -> None:
    """Test ExportedAttachment for skipped file."""
    att = ExportedAttachment(
        identifier="uuid-456",
        filename=None,
        type_uti="com.apple.notes.table",
        exported=False,
        skip_reason="Rendered inline in note content",
    )
    assert att.exported is False
    assert att.skip_reason == "Rendered inline in note content"


def test_attachment_export_result() -> None:
    """Test AttachmentExportResult aggregates exports and skips."""
    exported = [
        ExportedAttachment("id1", "a.jpg", "public.jpeg", True, None),
    ]
    skipped = [
        ExportedAttachment("id2", None, "com.apple.notes.table", False, "No binary data"),
    ]
    result = AttachmentExportResult(
        exported=exported,
        skipped=skipped,
        manifest_path=None,
        attachments_dir=None,
    )
    assert len(result.exported) == 1
    assert len(result.skipped) == 1


def test_uti_to_extension_jpeg() -> None:
    """Test UTI to extension for JPEG images."""
    assert uti_to_extension("public.jpeg") == ".jpg"


def test_uti_to_extension_png() -> None:
    """Test UTI to extension for PNG images."""
    assert uti_to_extension("public.png") == ".png"


def test_uti_to_extension_pdf() -> None:
    """Test UTI to extension for PDF documents."""
    assert uti_to_extension("com.adobe.pdf") == ".pdf"
    assert uti_to_extension("public.pdf") == ".pdf"


def test_uti_to_extension_unknown() -> None:
    """Test UTI to extension for unknown types returns .bin."""
    assert uti_to_extension("com.unknown.type") == ".bin"


def test_uti_to_extension_drawing() -> None:
    """Test UTI to extension for Apple drawings."""
    assert uti_to_extension("com.apple.drawing") == ".png"
    assert uti_to_extension("com.apple.drawing.2") == ".png"


def test_sanitize_filename_simple() -> None:
    """Test sanitize_filename with normal filename."""
    assert sanitize_filename("photo.jpg") == "photo.jpg"


def test_sanitize_filename_spaces() -> None:
    """Test sanitize_filename replaces spaces with underscores."""
    assert sanitize_filename("my photo.jpg") == "my_photo.jpg"


def test_sanitize_filename_special_chars() -> None:
    """Test sanitize_filename removes special characters."""
    assert sanitize_filename("file/with:bad*chars?.jpg") == "filewithbadchars.jpg"


def test_sanitize_filename_unicode() -> None:
    """Test sanitize_filename handles unicode."""
    assert sanitize_filename("café_photo.jpg") == "café_photo.jpg"


def test_sanitize_filename_empty() -> None:
    """Test sanitize_filename with empty string."""
    assert sanitize_filename("") == "attachment"


def test_sanitize_filename_only_bad_chars() -> None:
    """Test sanitize_filename with only bad characters."""
    assert sanitize_filename("***") == "attachment"


def test_make_unique_filename_no_conflict() -> None:
    """Test make_unique_filename when no conflict exists."""
    used: set[str] = set()
    result = make_unique_filename("photo.jpg", "uuid-123", used)
    assert result == "photo.jpg"
    assert "photo.jpg" in used


def test_make_unique_filename_with_conflict() -> None:
    """Test make_unique_filename adds UUID suffix on conflict."""
    used = {"photo.jpg"}
    result = make_unique_filename("photo.jpg", "abc123def456", used)
    assert result == "photo_abc123.jpg"
    assert "photo_abc123.jpg" in used


def test_make_unique_filename_no_extension() -> None:
    """Test make_unique_filename handles files without extension."""
    used = {"README"}
    result = make_unique_filename("README", "xyz789", used)
    assert result == "README_xyz789"


def test_get_skip_reason_table() -> None:
    """Test skip reason for table attachments."""
    reason = get_skip_reason("com.apple.notes.table")
    assert reason == "Rendered inline in note content"


def test_get_skip_reason_link() -> None:
    """Test skip reason for URL links."""
    reason = get_skip_reason("public.url")
    assert reason == "URL link, no file data"


def test_get_skip_reason_map() -> None:
    """Test skip reason for map attachments."""
    reason = get_skip_reason("com.apple.mapkit.map-item")
    assert reason == "Location data, no file data"


def test_get_skip_reason_exportable() -> None:
    """Test skip reason is None for exportable types."""
    assert get_skip_reason("public.jpeg") is None
    assert get_skip_reason("public.png") is None
    assert get_skip_reason("com.adobe.pdf") is None


def test_generate_manifest(tmp_path: Path) -> None:
    """Test manifest generation with exported and skipped attachments."""
    exported = [
        ExportedAttachment("uuid-1", "photo.jpg", "public.jpeg", True, None),
        ExportedAttachment("uuid-2", "doc.pdf", "com.adobe.pdf", True, None),
    ]
    skipped = [
        ExportedAttachment("uuid-3", None, "com.apple.notes.table", False, "Rendered inline"),
    ]

    manifest_path = tmp_path / "manifest.json"
    generate_manifest(
        manifest_path,
        note_id=42,
        note_title="Test Note",
        exported=exported,
        skipped=skipped,
    )

    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())

    assert data["note_id"] == 42
    assert data["note_title"] == "Test Note"
    assert "exported_at" in data
    assert len(data["attachments"]) == 3

    # Check exported attachment
    att1 = data["attachments"][0]
    assert att1["identifier"] == "uuid-1"
    assert att1["filename"] == "photo.jpg"
    assert att1["exported"] is True

    # Check skipped attachment
    att3 = data["attachments"][2]
    assert att3["identifier"] == "uuid-3"
    assert att3["filename"] is None
    assert att3["exported"] is False
    assert att3["skip_reason"] == "Rendered inline"
