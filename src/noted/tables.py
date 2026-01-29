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


# Known CRDT metadata strings to filter out
_CRDT_NOISE = frozenset({
    "identity",
    "dentity",  # Partial match
    "cellColumns",
    "UUIDIndex",
    "UIDI",  # Partial match
    "crRows",
    "crTableColumnDirection",
    "self",
    "crColumns",
    "CRTableColumnDirectionLeftToRight",
})

# Substrings that indicate CRDT noise
_CRDT_SUBSTRINGS = (
    "CRDT",
    "CRTable",
    "LeftToRight",
    "00000000-0000-0000",
)


def _is_crdt_noise(s: str) -> bool:
    """Check if string is CRDT metadata noise."""
    # Exact matches
    if s in _CRDT_NOISE:
        return True
    # Substring matches
    for noise in _CRDT_SUBSTRINGS:
        if noise in s:
            return True
    # Prefix matches
    if s.startswith("com.apple."):
        return True
    # Very short garbage
    if len(s) <= 3:
        return True
    # Starts with non-printable looking characters
    if s[0] in '&"#$%' and len(s) > 1 and s[1] in '&"#$%0123456789':
        return True
    # Binary-looking garbage (multiple non-printable-like chars)
    non_alpha = sum(1 for c in s if not c.isalnum() and c not in " .-$(),/:@\n")
    if non_alpha > len(s) * 0.3 and len(s) < 20:
        return True
    return False


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
                s = "".join(current).strip()
                if s and not _is_crdt_noise(s):
                    strings.append(s)
            current = []

    if len(current) > 3:
        s = "".join(current).strip()
        if s and not _is_crdt_noise(s):
            strings.append(s)

    return strings


def _extract_strings_recursive(
    data: bytes, depth: int = 0, max_depth: int = 5
) -> list[str]:
    """Recursively decode protobuf and extract strings.

    Args:
        data: Binary protobuf data.
        depth: Current recursion depth.
        max_depth: Maximum recursion depth.

    Returns:
        List of extracted cell strings.
    """
    if depth > max_depth or len(data) < 5:
        return []

    strings: list[str] = []
    try:
        fields = decode_fields(data)
        for field_num, vals in fields.items():
            for wire_type, val in vals:
                if not isinstance(val, bytes):
                    continue

                # Try to decode as UTF-8 string
                try:
                    s = val.decode("utf-8").strip()
                    if s and len(s) > 1 and not _is_crdt_noise(s):
                        # Check if it looks like readable text
                        printable = sum(1 for c in s if c.isprintable() or c in "\n\t")
                        if printable > len(s) * 0.8:
                            strings.append(s)
                except UnicodeDecodeError:
                    pass

                # Recurse into length-delimited fields
                if wire_type == 2 and len(val) > 5:
                    strings.extend(_extract_strings_recursive(val, depth + 1))
    except Exception:
        pass

    return strings


def _extract_cells_from_field10(obj: dict[int, list[tuple[int, Any]]]) -> list[str]:
    """Extract cell text values from field 10 entries.

    Apple Notes tables store cell content in field 10 of table_object entries.
    The text is in subfield 2 of each field 10 structure.

    Args:
        obj: Decoded MergableDataObject fields.

    Returns:
        List of cell text values in storage order.
    """
    cells: list[str] = []

    if 3 not in obj:
        return cells

    for _, entry_data in obj[3]:
        if not isinstance(entry_data, bytes):
            continue

        entry = decode_fields(entry_data)
        if 10 not in entry:
            continue

        # Field 10 contains the cell structure
        f10_data = entry[10][0][1]
        if not isinstance(f10_data, bytes):
            continue

        f10 = decode_fields(f10_data)
        if 2 not in f10:
            continue

        # Field 2 contains the text
        text_data = f10[2][0][1]
        if isinstance(text_data, bytes):
            try:
                text = text_data.decode("utf-8")
                cells.append(text)
            except UnicodeDecodeError:
                pass

    return cells


def _parse_mergeable_data_object(obj_data: bytes) -> Table | None:
    """Parse MergableDataObject to extract table structure.

    Apple Notes tables store cells column-by-column, with each column's
    header as the last cell in that column's range. This function extracts
    cells and reconstructs the grid.

    Args:
        obj_data: Raw bytes of the MergableDataObject.

    Returns:
        Table with parsed cells, or None if parsing fails.
    """
    obj = decode_fields(obj_data)

    # Extract cells from field 10 entries
    cell_values = _extract_cells_from_field10(obj)

    if not cell_values:
        # Fallback to recursive string extraction
        cell_values = _extract_strings_recursive(obj_data)
        # Deduplicate
        seen: set[str] = set()
        unique: list[str] = []
        for s in cell_values:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        cell_values = unique

    if not cell_values:
        return None

    # Detect column count by finding header positions
    # In Apple Notes CRDT tables, headers are at the END of each column segment
    # Find headers by looking for known header patterns in exact positions

    # Find potential headers - only use exact matches from common set
    common_headers = {
        "Date", "Miles", "Cost", "Performed By", "Service Desc",
        "Name", "Description", "Price", "Quantity", "Total", "Qty",
        "Item", "Amount", "Status", "Notes", "Category", "Type",
    }

    header_positions: list[tuple[int, str]] = []
    for i, val in enumerate(cell_values):
        # Only exact matches with common headers
        if val.strip() in common_headers:
            header_positions.append((i, val.strip()))

    # If we found headers, they mark the end of each column's data
    if len(header_positions) >= 2:
        num_cols = len(header_positions)
        # Calculate rows per column (cells before first header + 1 for header)
        cells_per_col = header_positions[0][0] + 1
        num_rows = cells_per_col

        # Build grid: columns are stored sequentially
        # Each column has (num_rows - 1) data cells followed by 1 header
        grid_cells: dict[tuple[int, int], str] = {}

        # Map storage columns to display columns based on header order
        # Headers are at positions 0*cells_per_col + (cells_per_col-1), etc.
        storage_col_headers: list[str] = []
        for col_idx in range(num_cols):
            header_pos = (col_idx + 1) * cells_per_col - 1
            if header_pos < len(cell_values):
                storage_col_headers.append(cell_values[header_pos])

        # For each storage column, extract cells
        for storage_col in range(num_cols):
            col_start = storage_col * cells_per_col
            col_end = col_start + cells_per_col

            # Header goes in row 0
            header_idx = col_end - 1
            if header_idx < len(cell_values):
                grid_cells[(0, storage_col)] = cell_values[header_idx]

            # Data cells go in rows 1+
            for data_idx in range(col_start, min(col_end - 1, len(cell_values))):
                row = data_idx - col_start + 1
                grid_cells[(row, storage_col)] = cell_values[data_idx]

        return Table(rows=num_rows, columns=num_cols, cells=grid_cells)

    # Fallback: single column
    cells: dict[tuple[int, int], str] = {}
    for i, val in enumerate(cell_values):
        cells[(i, 0)] = val

    return Table(rows=len(cell_values), columns=1, cells=cells)


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
