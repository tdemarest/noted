"""Tests for noted.protobuf."""

import gzip

import betterproto

from noted.protobuf import NoteStoreProto, is_note_locked, parse_note_data


def test_notestoreproto_structure() -> None:
    """Test that NoteStoreProto has expected structure."""
    proto = NoteStoreProto()
    assert hasattr(proto, "document")
    assert isinstance(proto, betterproto.Message)


def test_parse_note_data_simple() -> None:
    """Test parsing a simple note with just text."""
    # Create a minimal valid protobuf manually
    # NoteStoreProto.document.note.note_text = "Hello"
    # Field 2 (document) -> Field 3 (note) -> Field 2 (note_text)

    # Build inner note: field 2 (string) = "Hello"
    note_proto = b"\x12\x05Hello"  # field 2, length 5, "Hello"

    # Build document: field 3 (message) = note_proto
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto  # field 3, length, data

    # Build root: field 2 (message) = doc_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto  # field 2, length, data

    # Gzip compress it
    compressed = gzip.compress(root_proto)

    result = parse_note_data(compressed)
    assert result.text == "Hello"


def test_parse_note_data_empty_text() -> None:
    """Test parsing a note with empty text."""
    # Empty note_text
    note_proto = b"\x12\x00"  # field 2, length 0
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    result = parse_note_data(compressed)
    assert result.text == ""


def test_is_note_locked_gzip() -> None:
    """Test that gzip data is not locked."""
    # Valid gzip magic bytes
    data = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03test"
    assert is_note_locked(data) is False


def test_is_note_locked_encrypted() -> None:
    """Test that non-gzip data is considered locked."""
    # Random bytes (not gzip)
    data = b"\x00\x01\x02\x03\x04\x05"
    assert is_note_locked(data) is True


def test_is_note_locked_empty() -> None:
    """Test that empty data is not locked (just missing)."""
    assert is_note_locked(b"") is False
    assert is_note_locked(None) is False


def test_parse_note_replaces_attachment_placeholders() -> None:
    """Test that U+FFFC attachment placeholders are replaced with markers."""
    from noted.protobuf import _process_attachments

    # Text with object replacement character
    text = "Hello \ufffc world"

    # AttributeRun: length=6 (for "Hello "), then length=1 with attachment_info, then length=6
    # The attachment run covers the U+FFFC character
    class MockAttachmentInfo:
        attachment_identifier: str = "abc123"
        type_uti: str = "public.jpeg"

    class MockAttributeRun:
        length: int
        attachment_info: object

        def __init__(self, length: int, attachment_info: object = None) -> None:
            self.length = length
            self.attachment_info = attachment_info

    runs = [
        MockAttributeRun(6, None),  # "Hello "
        MockAttributeRun(1, MockAttachmentInfo()),  # U+FFFC -> [Image]
        MockAttributeRun(6, None),  # " world"
    ]

    result_text, attachments = _process_attachments(text, runs)
    assert "\ufffc" not in result_text
    assert "[Image]" in result_text
    assert len(attachments) == 1
    assert attachments[0].identifier == "abc123"
    assert attachments[0].type_uti == "public.jpeg"


def test_parse_note_handles_multiple_attachments() -> None:
    """Test handling multiple attachments in a note."""
    from noted.protobuf import _process_attachments

    # Two attachments
    text = "A\ufffcB\ufffcC"

    class MockAttachmentInfo:
        def __init__(self, type_uti: str) -> None:
            self.attachment_identifier = "id"
            self.type_uti = type_uti

    class MockAttributeRun:
        def __init__(self, length: int, attachment_info: object = None) -> None:
            self.length = length
            self.attachment_info = attachment_info

    runs = [
        MockAttributeRun(1, None),  # "A"
        MockAttributeRun(1, MockAttachmentInfo("public.png")),  # first U+FFFC
        MockAttributeRun(1, None),  # "B"
        MockAttributeRun(1, MockAttachmentInfo("com.adobe.pdf")),  # second U+FFFC
        MockAttributeRun(1, None),  # "C"
    ]

    result_text, attachments = _process_attachments(text, runs)
    assert result_text.count("[") == 2  # Two attachment markers
    assert "\ufffc" not in result_text
    assert len(attachments) == 2


def test_parse_note_with_attachment_names() -> None:
    """Test that attachment names are included when provided."""
    from noted.protobuf import _process_attachments

    text = "See: \ufffc"

    class MockAttachmentInfo:
        attachment_identifier: str = "uuid-123"
        type_uti: str = "com.adobe.pdf"

    class MockAttributeRun:
        def __init__(self, length: int, attachment_info: object = None) -> None:
            self.length = length
            self.attachment_info = attachment_info

    runs = [
        MockAttributeRun(5, None),  # "See: "
        MockAttributeRun(1, MockAttachmentInfo()),  # U+FFFC
    ]

    # With attachment names provided
    names = {"uuid-123": "report.pdf"}
    result_text, attachments = _process_attachments(text, runs, names)

    assert "[PDF: report.pdf]" in result_text
    assert attachments[0].title == "report.pdf"
