"""Tests for noted.tables."""

import gzip
from typing import Any

from noted.tables import decode_fields, decode_varint, parse_table_data


def test_decode_varint_single_byte() -> None:
    """Test decoding single-byte varint."""
    data = bytes([0x08])  # Value 8
    value, pos = decode_varint(data, 0)
    assert value == 8
    assert pos == 1


def test_decode_varint_multi_byte() -> None:
    """Test decoding multi-byte varint."""
    data = bytes([0xAC, 0x02])  # Value 300
    value, pos = decode_varint(data, 0)
    assert value == 300
    assert pos == 2


def test_decode_fields_simple() -> None:
    """Test decoding simple protobuf fields."""
    # Field 1 (varint) = 150, Field 2 (string) = "test"
    data = bytes([
        0x08, 0x96, 0x01,  # field 1, varint 150
        0x12, 0x04, 0x74, 0x65, 0x73, 0x74,  # field 2, string "test"
    ])
    fields: dict[int, list[tuple[int, Any]]] = decode_fields(data)
    assert 1 in fields
    assert fields[1][0][1] == 150  # (wire_type, value)
    assert 2 in fields
    assert fields[2][0][1] == b"test"


def test_parse_table_data_returns_none_for_invalid() -> None:
    """Test that invalid data returns None."""
    result = parse_table_data(b"not gzip data")
    assert result is None


def test_parse_table_data_returns_none_for_empty() -> None:
    """Test that empty gzip returns None."""
    empty_gzip = gzip.compress(b"")
    result = parse_table_data(empty_gzip)
    assert result is None
