"""Protobuf parsing for Apple Notes content.

Apple Notes stores note content as gzip-compressed protobuf data.
This module defines the betterproto schema and parsing functions.
"""

import gzip
from dataclasses import dataclass

import betterproto

from noted.models import NoteContent

# Gzip magic bytes
GZIP_MAGIC = b"\x1f\x8b"


def is_note_locked(data: bytes | None) -> bool:
    """Check if note data is encrypted (locked).

    Locked notes don't have gzip-compressed data.

    Args:
        data: Raw bytes from ZICNOTEDATA.ZDATA.

    Returns:
        True if the note appears to be locked/encrypted.
    """
    if not data or len(data) < 2:
        return False
    return data[:2] != GZIP_MAGIC


@dataclass
class Note(betterproto.Message):
    """Protobuf Note message containing the text content.

    Field numbers match Apple's schema:
    - Field 2: note_text (string)
    - Field 5: attribute_run (repeated, not implemented yet)
    """

    note_text: str = betterproto.string_field(2)


@dataclass
class Document(betterproto.Message):
    """Protobuf Document message wrapping a Note.

    Field numbers match Apple's schema:
    - Field 2: version (not implemented)
    - Field 3: note (Note message)
    """

    note: Note = betterproto.message_field(3)


@dataclass
class NoteStoreProto(betterproto.Message):
    """Root protobuf message for Apple Notes content.

    Field numbers match Apple's schema:
    - Field 2: document (Document message)
    """

    document: Document = betterproto.message_field(2)


def parse_note_data(data: bytes) -> NoteContent:
    """Parse gzip-compressed protobuf note data.

    Args:
        data: Gzip-compressed protobuf bytes from ZICNOTEDATA.ZDATA.

    Returns:
        NoteContent with extracted plain text.

    Raises:
        gzip.BadGzipFile: If data is not valid gzip.
        Exception: If protobuf parsing fails.
    """
    decompressed = gzip.decompress(data)
    proto = NoteStoreProto().parse(decompressed)
    text = proto.document.note.note_text if proto.document and proto.document.note else ""
    return NoteContent(text=text)
