"""Tests for noted.attachments."""

import json
import sqlite3
from pathlib import Path

from noted.attachments import (
    AttachmentExportResult,
    ExportedAttachment,
    export_attachments,
    generate_manifest,
    get_skip_reason,
    make_unique_filename,
    sanitize_filename,
    uti_to_extension,
)
from noted.models import Attachment


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


def test_export_attachments_single_image(tmp_path: Path) -> None:
    """Test exporting a single image attachment."""
    # Set up test database
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)
    image_data = b"\x89PNG\r\n\x1a\nfake_png_data"
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?)",
        (1, "img-uuid", "public.png", "photo.png", image_data),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    attachments = [
        Attachment(identifier="img-uuid", type_uti="public.png", title="photo.png"),
    ]

    result = export_attachments(
        conn=conn,
        attachments=attachments,
        output_dir=tmp_path,
        base_name="TestNote",
        note_id=1,
        note_title="Test Note",
    )

    conn.close()

    # Verify results
    assert len(result.exported) == 1
    assert len(result.skipped) == 0
    assert result.attachments_dir is not None
    assert result.attachments_dir.exists()

    # Check exported file
    exported_file = result.attachments_dir / "photo.png"
    assert exported_file.exists()
    assert exported_file.read_bytes() == image_data

    # Check manifest
    assert result.manifest_path is not None
    assert result.manifest_path.exists()


def test_export_attachments_skips_tables(tmp_path: Path) -> None:
    """Test that table attachments are skipped."""
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)
    # Table has no ZDATA
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?)",
        (1, "table-uuid", "com.apple.notes.table", None, None),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    attachments = [
        Attachment(identifier="table-uuid", type_uti="com.apple.notes.table"),
    ]

    result = export_attachments(
        conn=conn,
        attachments=attachments,
        output_dir=tmp_path,
        base_name="TestNote",
        note_id=1,
        note_title="Test Note",
    )

    conn.close()

    assert len(result.exported) == 0
    assert len(result.skipped) == 1
    assert result.skipped[0].skip_reason is not None


def test_export_attachments_empty_list(tmp_path: Path) -> None:
    """Test export with empty attachment list."""
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = export_attachments(
        conn=conn,
        attachments=[],
        output_dir=tmp_path,
        base_name="TestNote",
        note_id=1,
        note_title="Test Note",
    )

    conn.close()

    assert len(result.exported) == 0
    assert len(result.skipped) == 0
    assert result.attachments_dir is None
    assert result.manifest_path is None
