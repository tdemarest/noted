"""Protobuf parsing for Apple Notes content.

Apple Notes stores note content as gzip-compressed protobuf data.
This module defines the betterproto schema and parsing functions.
"""

import gzip
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

import betterproto

from noted.models import (
    Attachment,
    FormattedRun,
    NoteContent,
    ParagraphStyle,
    TextStyle,
)

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
    attachment_names: dict[str, str] | None = None,
) -> tuple[str, list[Attachment]]:
    """Replace attachment placeholders with human-readable markers.

    Apple Notes uses U+FFFC (Object Replacement Character) as a placeholder
    for embedded attachments. This function replaces those with markers like
    [Image: filename.jpg] or [PDF] based on the attachment's UTI type.

    Args:
        text: The note text containing U+FFFC placeholders.
        attribute_runs: List of AttributeRun objects with attachment info.
        attachment_names: Optional mapping of identifier -> title for attachments.

    Returns:
        Tuple of (processed text, list of Attachment objects found).
    """
    attachments: list[Attachment] = []

    if not attribute_runs or OBJECT_REPLACEMENT_CHAR not in text:
        return text, attachments

    result = []
    text_pos = 0
    names = attachment_names or {}

    for run in attribute_runs:
        run_length = run.length
        run_text = text[text_pos : text_pos + run_length]

        if run.attachment_info and OBJECT_REPLACEMENT_CHAR in run_text:
            # Get attachment details
            info = run.attachment_info
            identifier = getattr(info, "attachment_identifier", "") or ""
            uti = getattr(info, "type_uti", "") or ""
            title = names.get(identifier)

            # Create Attachment object
            attachments.append(Attachment(
                identifier=identifier,
                type_uti=uti,
                title=title,
            ))

            # Replace U+FFFC with attachment marker
            type_name = _uti_to_type(uti)
            if type_name == "Table" and identifier:
                # Use unique marker for tables to enable inline rendering
                marker = f"[Table:{identifier}]"
            elif title:
                marker = f"[{type_name}: {title}]"
            else:
                marker = f"[{type_name}]"
            run_text = run_text.replace(OBJECT_REPLACEMENT_CHAR, marker)

        result.append(run_text)
        text_pos += run_length

    # Append any remaining text (shouldn't happen with valid data)
    if text_pos < len(text):
        result.append(text[text_pos:])

    return "".join(result), attachments


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


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a protobuf varint from data at position."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _decode_fields(data: bytes) -> dict[int, list[tuple[int, Any]]]:
    """Decode all fields from protobuf data."""
    fields: dict[int, list[tuple[int, Any]]] = {}
    pos = 0
    while pos < len(data):
        if pos >= len(data):
            break
        tag, pos = _decode_varint(data, pos)
        if tag == 0:
            break
        field_num = tag >> 3
        wire_type = tag & 0x7
        value: Any
        if wire_type == 0:
            value, pos = _decode_varint(data, pos)
        elif wire_type == 2:
            length, pos = _decode_varint(data, pos)
            value = data[pos : pos + length]
            pos += length
        elif wire_type == 5:
            value = data[pos : pos + 4]
            pos += 4
        elif wire_type == 1:
            value = data[pos : pos + 8]
            pos += 8
        else:
            break
        if field_num not in fields:
            fields[field_num] = []
        fields[field_num].append((wire_type, value))
    return fields


def _extract_formatting(
    decompressed: bytes,
    text: str,
) -> list[FormattedRun]:
    """Extract formatting information from decompressed protobuf.

    Uses raw protobuf decoding to access all formatting fields that
    aren't covered by the betterproto schema.

    Args:
        decompressed: Decompressed protobuf bytes.
        text: The note's plain text content.

    Returns:
        List of FormattedRun objects with formatting details.
    """
    formatted_runs: list[FormattedRun] = []

    try:
        top = _decode_fields(decompressed)
        if 2 not in top:
            return formatted_runs

        doc = _decode_fields(top[2][0][1])
        if 3 not in doc:
            return formatted_runs

        note = _decode_fields(doc[3][0][1])
        if 5 not in note:
            return formatted_runs

        text_pos = 0
        for _, run_data in note[5]:
            if not isinstance(run_data, bytes):
                continue

            run = _decode_fields(run_data)

            # Field 1: length
            length = run[1][0][1] if 1 in run else 0
            run_text = text[text_pos : text_pos + length] if text_pos + length <= len(text) else ""
            text_pos += length

            # Extract text styling (run-level fields)
            text_style = TextStyle()
            if 5 in run:
                font_weight = run[5][0][1]
                text_style.bold = font_weight in (1, 3)
                text_style.italic = font_weight in (2, 3)
            if 6 in run:
                text_style.underline = run[6][0][1] == 1
            if 7 in run:
                text_style.strikethrough = run[7][0][1] == 1
            if 14 in run:
                text_style.highlight = run[14][0][1] == 1

            # Extract paragraph style (field 2)
            para_style = ParagraphStyle()
            if 2 in run:
                style_data = run[2][0][1]
                if isinstance(style_data, bytes):
                    style = _decode_fields(style_data)

                    if 1 in style:
                        para_style.paragraph_type = style[1][0][1]
                    if 2 in style:
                        para_style.alignment = style[2][0][1]
                    if 3 in style:
                        para_style.indent_level = style[3][0][1]
                    if 4 in style:
                        # style.4 is used for text indentation (not list indent)
                        para_style.indent_level = max(
                            para_style.indent_level,
                            style[4][0][1],
                        )
                    if 5 in style:
                        # style.5 is a message containing checked state for checklists
                        # The checked flag is in field 2 of this nested message
                        checked_data = style[5][0][1]
                        if isinstance(checked_data, bytes):
                            checked_msg = _decode_fields(checked_data)
                            if 2 in checked_msg:
                                para_style.is_checked = checked_msg[2][0][1] == 1
                    if 7 in style:
                        para_style.list_index = style[7][0][1]
                    if 8 in style:
                        para_style.is_quote = style[8][0][1] == 1

            # Extract link (field 9)
            link = None
            if 9 in run:
                val = run[9][0][1]
                if isinstance(val, bytes):
                    try:
                        link = val.decode("utf-8")
                    except UnicodeDecodeError:
                        pass

            formatted_runs.append(FormattedRun(
                text=run_text,
                length=length,
                text_style=text_style,
                paragraph_style=para_style,
                link=link,
            ))

    except Exception:
        # If formatting extraction fails, return empty list
        pass

    return formatted_runs


def parse_note_data(
    data: bytes,
    attachment_names: dict[str, str] | None = None,
    include_formatting: bool = False,
) -> NoteContent:
    """Parse gzip-compressed protobuf note data.

    Args:
        data: Gzip-compressed protobuf bytes from ZICNOTEDATA.ZDATA.
        attachment_names: Optional mapping of attachment identifier -> title.
            If provided, attachment markers will include the title.
        include_formatting: If True, extract detailed formatting information.

    Returns:
        NoteContent with extracted plain text and attachment info.
        Attachment placeholders (U+FFFC) are replaced with markers
        like [Image: photo.jpg] or [PDF].

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
    attachments: list[Attachment] = []

    # Replace attachment placeholders with human-readable markers
    if note.attribute_run:
        text, attachments = _process_attachments(text, note.attribute_run, attachment_names)

    # Extract formatting if requested
    formatted_runs = None
    if include_formatting:
        formatted_runs = _extract_formatting(decompressed, note.note_text or "")

    return NoteContent(
        text=text,
        attachments=attachments if attachments else None,
        formatted_runs=formatted_runs if formatted_runs else None,
    )
