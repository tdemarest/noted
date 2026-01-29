"""Table parsing for Apple Notes CRDT tables.

Apple Notes tables are stored as gzipped protobufs using a CRDT format
in ZMERGEABLEDATA1. This module handles decoding the complex nested
structure and reconstructing the table grid.
"""

import gzip
from typing import Any

from loguru import logger

from noted.models import Table


def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a protobuf varint from data at position.

    Args:
        data: Byte data to decode from.
        pos: Starting position in data.

    Returns:
        Tuple of (decoded value, new position after varint).
    """
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


def decode_fields(data: bytes) -> dict[int, list[tuple[int, Any]]]:
    """Decode all fields from protobuf data.

    Args:
        data: Raw protobuf bytes.

    Returns:
        Dict mapping field number to list of (wire_type, value) tuples.
        Wire types: 0=varint, 1=64-bit, 2=length-delimited, 5=32-bit.
    """
    fields: dict[int, list[tuple[int, Any]]] = {}
    pos = 0

    while pos < len(data):
        if pos >= len(data):
            break

        tag, pos = decode_varint(data, pos)
        if tag == 0:
            break

        field_num = tag >> 3
        wire_type = tag & 0x7

        value: Any
        if wire_type == 0:  # Varint
            value, pos = decode_varint(data, pos)
        elif wire_type == 2:  # Length-delimited
            length, pos = decode_varint(data, pos)
            value = data[pos : pos + length]
            pos += length
        elif wire_type == 5:  # 32-bit fixed
            value = data[pos : pos + 4]
            pos += 4
        elif wire_type == 1:  # 64-bit fixed
            value = data[pos : pos + 8]
            pos += 8
        else:
            logger.debug(f"Unknown wire type {wire_type} at position {pos}")
            break

        if field_num not in fields:
            fields[field_num] = []
        fields[field_num].append((wire_type, value))

    return fields


def _extract_strings_from_data(data: bytes) -> list[str]:
    """Extract readable strings from binary data.

    Used as fallback when structured parsing fails.

    Args:
        data: Binary data to scan.

    Returns:
        List of readable strings found (length > 3).
    """
    strings = []
    current: list[str] = []

    for b in data:
        if 32 <= b < 127:
            current.append(chr(b))
        else:
            if len(current) > 3:
                s = "".join(current)
                # Filter out protobuf type names
                if not s.startswith("com.apple.") and "CRDT" not in s:
                    strings.append(s)
            current = []

    if len(current) > 3:
        strings.append("".join(current))

    return strings


def _parse_mergeable_data_object(obj_data: bytes) -> Table | None:
    """Parse MergableDataObject to extract table structure.

    Args:
        obj_data: Raw bytes of the MergableDataObject.

    Returns:
        Table with parsed cells, or None if parsing fails.
    """
    obj = decode_fields(obj_data)

    # Field 4 = key_item (property names like "crRows", "crColumns", "cellColumns")
    key_items: list[str] = []
    if 4 in obj:
        for _, val in obj[4]:
            if isinstance(val, bytes):
                try:
                    key_items.append(val.decode("utf-8"))
                except UnicodeDecodeError:
                    key_items.append("")

    # Field 6 = uuid_item (row/column identifiers)
    uuid_items: list[bytes] = []
    if 6 in obj:
        for _, val in obj[6]:
            if isinstance(val, bytes):
                uuid_items.append(val)

    # Field 3 = table_object entries containing cell data
    # Extract all readable strings as cell candidates
    cells: dict[tuple[int, int], str] = {}
    cell_strings: list[str] = []

    if 3 in obj:
        for _, entry_data in obj[3]:
            if isinstance(entry_data, bytes):
                # Look for string content in entries
                entry = decode_fields(entry_data)
                # Field 9 typically contains string values
                if 9 in entry:
                    for _, val in entry[9]:
                        if isinstance(val, bytes):
                            try:
                                s = val.decode("utf-8")
                                if s.strip():
                                    cell_strings.append(s)
                            except UnicodeDecodeError:
                                pass

    # If structured parsing found no cells, try string extraction
    if not cell_strings:
        cell_strings = _extract_strings_from_data(obj_data)

    if not cell_strings:
        return None

    # Heuristic: arrange strings in a simple grid
    # Count rows by looking for date patterns or other structure
    # For now, create a single-column table
    for i, s in enumerate(cell_strings):
        cells[(i, 0)] = s

    return Table(rows=len(cell_strings), columns=1, cells=cells)


def _fallback_string_extraction(data: bytes) -> Table | None:
    """Fallback: extract any readable strings as table content.

    Args:
        data: Decompressed protobuf data.

    Returns:
        Table with strings as single column, or None if no strings found.
    """
    strings = _extract_strings_from_data(data)
    if not strings:
        return None

    cells = {(i, 0): s for i, s in enumerate(strings)}
    return Table(rows=len(strings), columns=1, cells=cells)


def parse_table_data(data: bytes) -> Table | None:
    """Parse gzipped CRDT table protobuf from ZMERGEABLEDATA1.

    Args:
        data: Gzipped protobuf bytes from database.

    Returns:
        Table with extracted cells, or None if parsing fails completely.
    """
    # Decompress
    try:
        decompressed = gzip.decompress(data)
    except Exception as e:
        logger.debug(f"Failed to decompress table data: {e}")
        return None

    if not decompressed:
        return None

    # Parse outer MergableDataProto
    try:
        top = decode_fields(decompressed)

        # Field 2 = inner wrapper
        if 2 not in top:
            logger.debug("Missing field 2 in MergableDataProto")
            return _fallback_string_extraction(decompressed)

        inner_data = top[2][0][1]
        if not isinstance(inner_data, bytes):
            return _fallback_string_extraction(decompressed)

        inner = decode_fields(inner_data)

        # Field 3 = MergableDataObject
        if 3 not in inner:
            logger.debug("Missing field 3 in inner wrapper")
            return _fallback_string_extraction(decompressed)

        obj_data = inner[3][0][1]
        if not isinstance(obj_data, bytes):
            return _fallback_string_extraction(decompressed)

        return _parse_mergeable_data_object(obj_data)

    except Exception as e:
        logger.debug(f"Failed to parse table structure: {e}")
        return _fallback_string_extraction(decompressed)
