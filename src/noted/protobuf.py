"""Protobuf parsing for Apple Notes content.

Apple Notes stores note content as gzip-compressed protobuf data.
This module defines the betterproto schema and parsing functions.
"""

import gzip
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

import betterproto

from noted.models import NoteContent

# Gzip magic bytes
GZIP_MAGIC = b"\x1f\x8b"

# Object Replacement Character - used as placeholder for attachments
OBJECT_REPLACEMENT_CHAR = "\ufffc"

# UTI to human-readable type mapping
UTI_TYPE_MAP: dict[str, str] = {
    "public.jpeg": "Image",
    "public.png": "Image",
    "public.heic": "Image",
    "public.gif": "Image",
    "public.tiff": "Image",
    "com.compuserve.gif": "Image",
    "com.adobe.pdf": "PDF",
    "public.pdf": "PDF",
    "com.apple.drawing": "Drawing",
    "com.apple.drawing.2": "Drawing",
    "public.url": "Link",
    "com.apple.mapkit.map-item": "Map",
    "public.vcard": "Contact",
    "com.apple.notes.table": "Table",
    "com.apple.notes.gallery": "Gallery",
    "com.apple.notes.inlinetextattachment": "Text",
    "com.apple.notes.inlinetextattachment.hashtag": "Tag",
    "com.apple.notes.inlinetextattachment.mention": "Mention",
}


def _uti_to_type(uti: str) -> str:
    """Convert UTI to human-readable type.

    Args:
        uti: Uniform Type Identifier (e.g., 'public.jpeg').

    Returns:
        Human-readable type (e.g., 'Image').
    """
    return UTI_TYPE_MAP.get(uti, "Attachment")


def _process_attachments(
    text: str,
    attribute_runs: list[Any],
) -> str:
    """Replace attachment placeholders with human-readable markers.

    Apple Notes uses U+FFFC (Object Replacement Character) as a placeholder
    for embedded attachments. This function replaces those with markers like
    [Image] or [PDF] based on the attachment's UTI type.

    Args:
        text: The note text containing U+FFFC placeholders.
        attribute_runs: List of AttributeRun objects with attachment info.

    Returns:
        Text with attachment placeholders replaced by markers.
    """
    if not attribute_runs or OBJECT_REPLACEMENT_CHAR not in text:
        return text

    result = []
    text_pos = 0

    for run in attribute_runs:
        run_length = run.length
        run_text = text[text_pos : text_pos + run_length]

        if run.attachment_info and OBJECT_REPLACEMENT_CHAR in run_text:
            # Replace U+FFFC with attachment marker
            uti = getattr(run.attachment_info, "type_uti", "") or ""
            type_name = _uti_to_type(uti)
            run_text = run_text.replace(OBJECT_REPLACEMENT_CHAR, f"[{type_name}]")

        result.append(run_text)
        text_pos += run_length

    # Append any remaining text (shouldn't happen with valid data)
    if text_pos < len(text):
        result.append(text[text_pos:])

    return "".join(result)


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
class AttachmentInfo(betterproto.Message):
    """Protobuf AttachmentInfo message for embedded attachments.

    Field numbers match Apple's schema:
    - Field 1: attachment_identifier (string)
    - Field 2: type_uti (string, e.g., 'public.jpeg')
    """

    attachment_identifier: str = betterproto.string_field(1)
    type_uti: str = betterproto.string_field(2)


@dataclass
class AttributeRun(betterproto.Message):
    """Protobuf AttributeRun message for text formatting and attachments.

    Field numbers match Apple's schema:
    - Field 1: length (int32) - number of characters this run applies to
    - Field 12: attachment_info (AttachmentInfo) - attachment details if present
    """

    length: int = betterproto.int32_field(1)
    attachment_info: AttachmentInfo | None = betterproto.message_field(12)


@dataclass
class Note(betterproto.Message):
    """Protobuf Note message containing the text content.

    Field numbers match Apple's schema:
    - Field 2: note_text (string)
    - Field 5: attribute_run (repeated)
    """

    note_text: str = betterproto.string_field(2)
    attribute_run: list[AttributeRun] = dataclass_field(
        default_factory=list,
        metadata={"betterproto": betterproto.FieldMetadata(5, "message")},
    )


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
        NoteContent with extracted plain text. Attachment placeholders
        (U+FFFC) are replaced with markers like [Image] or [PDF].

    Raises:
        gzip.BadGzipFile: If data is not valid gzip.
        Exception: If protobuf parsing fails.
    """
    decompressed = gzip.decompress(data)
    proto = NoteStoreProto().parse(decompressed)

    if not proto.document or not proto.document.note:
        return NoteContent(text="")

    note = proto.document.note
    text = note.note_text or ""

    # Replace attachment placeholders with human-readable markers
    if note.attribute_run:
        text = _process_attachments(text, note.attribute_run)

    return NoteContent(text=text)
