"""Tests for noted.protobuf."""

import gzip
import zlib
from dataclasses import dataclass

import betterproto2

from noted.display import get_note_html, note_to_markdown
from noted.models import Note
from noted.protobuf import NoteStoreProto, is_note_locked, parse_note_data


def test_notestoreproto_structure() -> None:
    """Test that NoteStoreProto has expected structure."""
    proto = NoteStoreProto()
    assert hasattr(proto, "document")
    assert isinstance(proto, betterproto2.Message)


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


def _varint(value: int) -> bytes:
    """Encode an unsigned protobuf varint."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field_varint(field: int, value: int) -> bytes:
    """Encode a varint field."""
    return _varint(field << 3) + _varint(value)


def _field_bytes(field: int, value: bytes) -> bytes:
    """Encode a length-delimited field."""
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _build_note(text: str, runs: list[bytes]) -> bytes:
    """Build an uncompressed NoteStoreProto with the given text and attribute runs."""
    note = _field_bytes(2, text.encode("utf-8")) + b"".join(_field_bytes(5, r) for r in runs)
    return _field_bytes(2, _field_bytes(3, note))


def _run(length: int, paragraph_style: bytes = b"", extra: bytes = b"") -> bytes:
    """Build an attribute run with an optional paragraph style and extra fields."""
    run = _field_varint(1, length)
    if paragraph_style:
        run += _field_bytes(2, paragraph_style)
    return run + extra


def test_writing_direction_is_not_indent() -> None:
    """Paragraph style field 3 (writing direction) must not be read as indent."""
    bullet_ltr = _field_varint(1, 100) + _field_varint(3, 1)
    nested = _field_varint(1, 100) + _field_varint(3, 1) + _field_varint(4, 1)
    data = gzip.compress(_build_note("a\nb\n", [_run(2, bullet_ltr), _run(2, nested)]))

    result = parse_note_data(data, include_formatting=True)

    assert result.formatted_runs is not None
    levels = [r.paragraph_style.indent_level for r in result.formatted_runs if r.paragraph_style]
    assert levels == [0, 1]


def test_zlib_body_is_readable() -> None:
    """A zlib-compressed body (older Notes versions) is not locked and parses."""
    data = zlib.compress(_build_note("Hello", [_run(5)]))

    assert is_note_locked(data) is False
    assert parse_note_data(data).text == "Hello"


def test_keyed_archive_body_is_locked() -> None:
    """A locked note's body (NSKeyedArchiver plist) is reported as locked."""
    assert is_note_locked(b"bplist00\x00\x01") is True


def test_literal_placeholder_does_not_shift_attachments() -> None:
    """A U+FFFC with no attachment info is dropped and does not consume an attachment."""
    info = _field_bytes(1, b"ATT-1") + _field_bytes(2, b"com.adobe.pdf")
    text = "x￼\n￼"
    runs = [_run(3), _run(1, extra=_field_bytes(12, info))]
    data = gzip.compress(_build_note(text, runs))

    content = parse_note_data(data, {"ATT-1": "doc.pdf"}, include_formatting=True)

    assert content.text == "x\n[PDF: doc.pdf]"
    assert content.formatted_runs is not None
    assert [r.attachment_identifier for r in content.formatted_runs] == [None, "ATT-1"]
    markdown = note_to_markdown(content, {})
    assert "[PDF: doc.pdf]" in markdown
    assert "￼" not in markdown


def test_note_link_and_divider_render() -> None:
    """Note links render as their title and divider lines as a rule."""
    link = _field_bytes(1, b"L-1") + _field_bytes(2, b"com.apple.notes.inlinetextattachment.link")
    divider = _field_bytes(1, b"D-1") + _field_bytes(
        2, b"com.apple.notes.inlinetextattachment.dividerline"
    )
    text = "￼\n￼"
    runs = [
        _run(1, extra=_field_bytes(12, link)),
        _run(1),
        _run(1, extra=_field_bytes(12, divider)),
    ]
    data = gzip.compress(_build_note(text, runs))
    names = {"L-1": "Other note", "D-1": "-"}

    content = parse_note_data(data, names, include_formatting=True)

    assert content.text == "Other note\n---"
    markdown = note_to_markdown(content, {})
    assert "Other note" in markdown
    assert "---" in markdown
    assert "[Attachment" not in markdown


def test_note_link_and_url_card_render_as_links() -> None:
    """Note links and URL cards with a URL render as links; unsafe schemes are not linked."""
    link = _field_bytes(1, b"L-1") + _field_bytes(2, b"com.apple.notes.inlinetextattachment.link")
    card = _field_bytes(1, b"U-1") + _field_bytes(2, b"public.url")
    data = gzip.compress(
        _build_note(
            "￼\n￼",
            [_run(1, extra=_field_bytes(12, link)), _run(1), _run(1, extra=_field_bytes(12, card))],
        )
    )
    content = parse_note_data(data, {"L-1": "Other [note]"}, include_formatting=True)
    assert content.attachments is not None
    content.attachments[0].url = "applenotes:note/NOTE-UUID"
    content.attachments[1].url = "javascript:alert(1)"

    markdown = note_to_markdown(content, {})
    assert "[Other \\[note\\]](<applenotes:note/NOTE-UUID>)" in markdown

    page = get_note_html(
        Note(id=1, identifier="N", title="T", folder=None, created=None, modified=None), content
    )
    assert '<a href="applenotes:note/NOTE-UUID">Other [note]</a>' in page
    assert 'href="javascript:' not in page


class _Alignment(betterproto2.Enum):
    """Synthetic enum with fewer members than the wire data uses."""

    LEFT = 0
    CENTER = 1


@dataclass
class _Styled(betterproto2.Message):
    """Synthetic message with an enum field, standing in for Apple's styles."""

    alignment: _Alignment = betterproto2.field(
        1, betterproto2.TYPE_ENUM, default_factory=lambda: _Alignment(0)
    )


def test_unknown_fields_and_enum_values_are_tolerated() -> None:
    """Unknown field numbers, wire types and enum values parse without error.

    Apple adds fields and enum values our schema does not declare, so every
    level of the note payload carries extras: varint, length-delimited,
    fixed32 and fixed64 fields with unknown numbers, plus an out-of-range
    paragraph style type (an enum on Apple's side).
    """
    fixed32 = _varint((50 << 3) | 5) + (7).to_bytes(4, "little")
    fixed64 = _varint((51 << 3) | 1) + (7).to_bytes(8, "little")
    unknown = _field_varint(90, 999) + _field_bytes(91, b"\x08\x01") + fixed32 + fixed64
    style = _field_varint(1, 999) + unknown
    run = _run(5, paragraph_style=style, extra=unknown)
    note = _field_bytes(2, b"Hello") + _field_bytes(5, run) + unknown
    document = _field_varint(2, 1) + _field_bytes(3, note) + unknown
    payload = _field_varint(1, 999) + _field_bytes(2, document) + unknown

    proto = NoteStoreProto.parse(payload)
    assert proto.document is not None and proto.document.note is not None
    assert proto.document.note.note_text == "Hello"
    assert [r.length for r in proto.document.note.attribute_run] == [5]

    content = parse_note_data(gzip.compress(payload), include_formatting=True)
    assert content.text == "Hello"
    assert content.formatted_runs is not None

    styled = _Styled.parse(_field_varint(1, 42) + unknown)
    assert int(styled.alignment) == 42
