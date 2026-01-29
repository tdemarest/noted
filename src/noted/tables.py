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
_CRDT_NOISE = frozenset(
    {
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
    }
)

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


def _extract_strings_recursive(data: bytes, depth: int = 0, max_depth: int = 5) -> list[str]:
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


def _parse_mergeable_data_object(obj_data: bytes, summary: str = "") -> Table | None:
    """Parse MergableDataObject to extract table structure.

    Apple Notes tables store cells column-by-column, with each column's
    header as the last cell in that column's range. This function extracts
    cells and reconstructs the grid.

    Args:
        obj_data: Raw bytes of the MergableDataObject.
        summary: Optional ZSUMMARY text for dimension inference.

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
        "Date",
        "Miles",
        "Cost",
        "Performed By",
        "Service Desc",
        "Name",
        "Description",
        "Price",
        "Quantity",
        "Total",
        "Qty",
        "Item",
        "Amount",
        "Status",
        "Notes",
        "Category",
        "Type",
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

        # Map storage columns to display columns based on header order
        # Headers are at positions 0*cells_per_col + (cells_per_col-1), etc.
        storage_col_headers: list[str] = []
        for col_idx in range(num_cols):
            header_pos = (col_idx + 1) * cells_per_col - 1
            if header_pos < len(cell_values):
                storage_col_headers.append(cell_values[header_pos])

        # For each storage column, extract cells into storage_grid
        storage_grid: dict[tuple[int, int], str] = {}
        for storage_col in range(num_cols):
            col_start = storage_col * cells_per_col
            col_end = col_start + cells_per_col

            # Header goes in row 0
            header_idx = col_end - 1
            if header_idx < len(cell_values):
                storage_grid[(0, storage_col)] = cell_values[header_idx]

            # Data cells go in rows 1+
            for data_idx in range(col_start, min(col_end - 1, len(cell_values))):
                row = data_idx - col_start + 1
                storage_grid[(row, storage_col)] = cell_values[data_idx]

        return Table(rows=num_rows, columns=num_cols, cells=storage_grid)

    # Fallback: use summary to infer dimensions
    # ZSUMMARY contains data in row-major display order
    if summary:
        summary_lines = [line.strip() for line in summary.split("\n") if line.strip()]
        num_summary_values = len(summary_lines)

        # Try to find a column count that divides evenly
        # Start with likely small column counts
        for num_cols in [2, 3, 4, 5]:
            if num_summary_values % num_cols == 0:
                num_rows = num_summary_values // num_cols

                # Verify that summary values match our cell_values (in some order)
                cell_set = set(cell_values)
                summary_set = set(summary_lines)

                # If sets match reasonably, use summary order for grid
                if len(cell_set & summary_set) >= len(summary_set) * 0.8:
                    cells: dict[tuple[int, int], str] = {}
                    for i, val in enumerate(summary_lines):
                        row = i // num_cols
                        col = i % num_cols
                        cells[(row, col)] = val
                    return Table(rows=num_rows, columns=num_cols, cells=cells)

    # Final fallback: single column
    cells = {}
    for i, val in enumerate(cell_values):
        cells[(i, 0)] = val

    return Table(rows=len(cell_values), columns=1, cells=cells)


def _reorder_columns_by_summary(table: Table, summary: str) -> Table:
    """Reorder table columns to match display order from ZSUMMARY.

    Apple Notes stores columns in creation order (storage order), but the
    ZSUMMARY field contains headers in display order. This function reorders
    the columns to match the display order.

    Args:
        table: Table with columns in storage order.
        summary: ZSUMMARY text with headers in display order (newline-separated).

    Returns:
        Table with columns reordered to display order.
    """
    if not summary or table.columns <= 1:
        return table

    # Extract display order headers from summary (first N lines = headers)
    summary_lines = [line.strip() for line in summary.split("\n") if line.strip()]
    display_headers = summary_lines[: table.columns]

    if len(display_headers) != table.columns:
        return table

    # Get storage order headers from row 0
    storage_headers = [table.get_cell(0, col) for col in range(table.columns)]

    # Build mapping: display_col -> storage_col
    col_mapping: list[int] = []
    for display_header in display_headers:
        found = False
        for storage_col, storage_header in enumerate(storage_headers):
            if storage_header == display_header and storage_col not in col_mapping:
                col_mapping.append(storage_col)
                found = True
                break
        if not found:
            # Header not found - can't reorder
            return table

    if len(col_mapping) != table.columns:
        return table

    # Reorder cells
    new_cells: dict[tuple[int, int], str] = {}
    for row in range(table.rows):
        for display_col, storage_col in enumerate(col_mapping):
            cell_value = table.get_cell(row, storage_col)
            if cell_value:
                new_cells[(row, display_col)] = cell_value

    return Table(rows=table.rows, columns=table.columns, cells=new_cells)


def _reorder_rows_by_summary(table: Table, summary: str) -> Table:
    """Reorder table rows to match display order from ZSUMMARY.

    ZSUMMARY contains all table cell values in display order. This function
    finds first-column values in ZSUMMARY that match storage row values,
    and uses the order of those matches to reorder rows.

    For duplicate first-column values, it uses second-column values as
    secondary keys for disambiguation.

    Args:
        table: Table with rows in storage order (columns already reordered).
        summary: ZSUMMARY text with all cell values in display order.

    Returns:
        Table with rows reordered to display order.
    """
    if not summary or table.rows <= 2:  # Header + 0-1 data rows
        return table

    # Get all unique first-column values from storage rows
    storage_first_cols: dict[str, list[int]] = {}
    for row in range(1, table.rows):
        first_col = (table.get_cell(row, 0) or "").strip()
        if first_col not in storage_first_cols:
            storage_first_cols[first_col] = []
        storage_first_cols[first_col].append(row)

    # Search ZSUMMARY for first-column values in display order
    summary_lines = summary.split("\n")
    num_cols = table.columns

    # Skip header lines
    data_lines = summary_lines[num_cols:]

    # Find display order by scanning for first-column matches
    # Use (first_col, col2, col3) tuple for disambiguation of duplicate keys
    display_order: list[tuple[str, str, str]] = []
    i = 0
    while i < len(data_lines):
        line = data_lines[i].strip()
        if line in storage_first_cols:
            # Found a first-column value - get columns 2 and 3 as secondary keys
            col2 = data_lines[i + 1].strip() if i + 1 < len(data_lines) else ""
            col3 = data_lines[i + 2].strip() if i + 2 < len(data_lines) else ""
            display_order.append((line, col2, col3))
        i += 1

    if len(display_order) != table.rows - 1:
        logger.debug(f"Row reorder: found {len(display_order)} keys, expected {table.rows - 1}")
        return table

    # Build mapping using multiple columns for disambiguation
    row_mapping: list[int] = []
    used_storage_rows: set[int] = set()

    for first_col, col2, col3 in display_order:
        candidates = [
            r for r in storage_first_cols.get(first_col, []) if r not in used_storage_rows
        ]

        if not candidates:
            logger.debug(f"Row reorder failed: no match for '{first_col}'")
            return table

        if len(candidates) == 1:
            # Unique match
            row_mapping.append(candidates[0])
            used_storage_rows.add(candidates[0])
        else:
            # Multiple candidates - try columns 2 and 3 to disambiguate
            found = False
            for storage_row in candidates:
                storage_col2 = (table.get_cell(storage_row, 1) or "").strip()
                storage_col3 = (table.get_cell(storage_row, 2) or "").strip()

                # Try matching on column 3 first (often more unique than column 2)
                if storage_col3 == col3:
                    row_mapping.append(storage_row)
                    used_storage_rows.add(storage_row)
                    found = True
                    break

            if not found:
                # Try column 2
                for storage_row in candidates:
                    storage_col2 = (table.get_cell(storage_row, 1) or "").strip()
                    if storage_col2 == col2:
                        row_mapping.append(storage_row)
                        used_storage_rows.add(storage_row)
                        found = True
                        break

            if not found:
                # Fall back to first available candidate
                row_mapping.append(candidates[0])
                used_storage_rows.add(candidates[0])

    if len(row_mapping) != table.rows - 1:
        logger.debug(
            f"Row reorder incomplete: mapped {len(row_mapping)}, expected {table.rows - 1}"
        )
        return table

    # Reorder cells: row 0 stays as header, data rows get reordered
    new_cells: dict[tuple[int, int], str] = {}

    # Copy header row (row 0)
    for col in range(table.columns):
        cell_value = table.get_cell(0, col)
        if cell_value:
            new_cells[(0, col)] = cell_value

    # Copy data rows in display order
    for display_row_idx, storage_row in enumerate(row_mapping):
        new_row = display_row_idx + 1  # +1 because row 0 is header
        for col in range(table.columns):
            cell_value = table.get_cell(storage_row, col)
            if cell_value:
                new_cells[(new_row, col)] = cell_value

    return Table(rows=table.rows, columns=table.columns, cells=new_cells)


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


def parse_table_data(data: bytes, summary: str = "") -> Table | None:
    """Parse gzipped CRDT table protobuf from ZMERGEABLEDATA1.

    Args:
        data: Gzipped protobuf bytes from database.
        summary: Optional ZSUMMARY text containing headers in display order.

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

        table = _parse_mergeable_data_object(obj_data, summary)
        if table and summary and table.columns > 1:
            table = _reorder_columns_by_summary(table, summary)
            table = _reorder_rows_by_summary(table, summary)
        return table

    except Exception as e:
        logger.debug(f"Failed to parse table structure: {e}")
        return _fallback_string_extraction(decompressed)
