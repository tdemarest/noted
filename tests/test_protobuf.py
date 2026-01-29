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
