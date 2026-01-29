"""Tests for noted.attachments."""

from noted.attachments import AttachmentExportResult, ExportedAttachment, uti_to_extension


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
