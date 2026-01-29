"""Tests for noted.protobuf."""

import gzip

import betterproto

from noted.protobuf import NoteStoreProto, parse_note_data


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
