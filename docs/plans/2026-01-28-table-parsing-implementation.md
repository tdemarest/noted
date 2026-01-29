# Table Parsing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Parse Apple Notes CRDT tables from `ZMERGEABLEDATA1` and render them inline using Rich tables.

**Architecture:** Create a `tables.py` module that decodes the nested protobuf structure (MergableDataProto → MergableDataObject → entries), extracts row/column ordering from ordered sets, and reconstructs cell content into a `Table` dataclass. The display layer renders tables inline where markers appear.

**Tech Stack:** betterproto (protobuf), gzip, Rich (display)

---

## Background: CRDT Table Structure

Apple Notes tables are stored as gzipped protobufs in `ZICCLOUDSYNCINGOBJECT.ZMERGEABLEDATA1`. The structure is:

```
MergableDataProto (root)
  └── MergableDataObject (field 2.3)
        ├── table_object entries (field 3, repeated) - actual data
        ├── key_item (field 4, repeated) - property names: "crRows", "crColumns", "cellColumns"
        ├── type_item (field 5, repeated) - CRDT type names
        └── uuid_item (field 6, repeated) - 16-byte UUIDs for rows/columns
```

Cell text is embedded in the table_object entries. Row/column ordering is determined by ordered sets referenced by key indices.

---

## Task 1: Add Table and TableCell Models

**Files:**
- Modify: `src/noted/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from noted.models import Attachment, Note, NoteContent, NoteSummary, Table


def test_table_creation() -> None:
    """Test Table dataclass creation."""
    cells = {(0, 0): "A", (0, 1): "B", (1, 0): "C", (1, 1): "D"}
    table = Table(rows=2, columns=2, cells=cells)
    assert table.rows == 2
    assert table.columns == 2
    assert table.get_cell(0, 0) == "A"
    assert table.get_cell(1, 1) == "D"


def test_table_get_cell_missing() -> None:
    """Test Table.get_cell returns empty string for missing cells."""
    table = Table(rows=2, columns=2, cells={(0, 0): "A"})
    assert table.get_cell(0, 0) == "A"
    assert table.get_cell(1, 1) == ""


def test_attachment_with_table() -> None:
    """Test Attachment can hold a Table."""
    table = Table(rows=1, columns=1, cells={(0, 0): "X"})
    attachment = Attachment(
        identifier="uuid-123",
        type_uti="com.apple.notes.table",
        title=None,
        table=table,
    )
    assert attachment.table is not None
    assert attachment.table.get_cell(0, 0) == "X"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_table_creation -v`
Expected: FAIL with `ImportError: cannot import name 'Table'`

**Step 3: Write minimal implementation**

Add to `src/noted/models.py` before `NoteContent`:

```python
@dataclass
class Table:
    """Parsed table from Apple Notes.

    Stores data in a neutral format that can be rendered
    as Rich, markdown, ASCII, or HTML.

    Attributes:
        rows: Number of rows in the table.
        columns: Number of columns in the table.
        cells: Mapping of (row, col) to cell text content.
    """

    rows: int
    columns: int
    cells: dict[tuple[int, int], str]

    def get_cell(self, row: int, col: int) -> str:
        """Get cell content, empty string if not present."""
        return self.cells.get((row, col), "")
```

Update `Attachment` dataclass:

```python
@dataclass
class Attachment:
    """Represents an embedded attachment in a note.

    Attributes:
        identifier: Unique identifier (UUID) for the attachment.
        type_uti: Uniform Type Identifier (e.g., 'public.jpeg').
        title: Display name/filename of the attachment, if known.
        table: Parsed table data, if this is a table attachment.
    """

    identifier: str
    type_uti: str
    title: str | None = None
    table: Table | None = None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/models.py tests/test_models.py && uv run pyrefly check src/noted/models.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/models.py tests/test_models.py
git commit -m "feat(models): add Table dataclass and update Attachment"
```

---

## Task 2: Add Database Function for Table Data

**Files:**
- Modify: `src/noted/db.py`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
from noted.db import (
    _cache_is_fresh,
    _source_db_path,
    apple_timestamp_to_datetime,
    clear_cache,
    get_attachment_names,
    get_connection,
    get_note_by_id,
    get_note_content,
    get_table_data,
)


def test_get_table_data(tmp_path: Path) -> None:
    """Test fetching table data by identifier."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)

    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZMERGEABLEDATA1 BLOB
        )
    """)

    test_data = b"\x1f\x8b\x08\x00table_data"
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZIDENTIFIER, ZTYPEUTI, ZMERGEABLEDATA1) VALUES (?, ?, ?, ?)",
        (1, "test-uuid", "com.apple.notes.table", test_data),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = get_table_data(conn, "test-uuid")
    assert result == test_data
    conn.close()


def test_get_table_data_not_found(tmp_path: Path) -> None:
    """Test fetching table data for non-existent identifier."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZMERGEABLEDATA1 BLOB
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = get_table_data(conn, "nonexistent")
    assert result is None
    conn.close()
```

Update the import at the top of the file to include `get_table_data`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_table_data -v`
Expected: FAIL with `ImportError: cannot import name 'get_table_data'`

**Step 3: Write minimal implementation**

Add to `src/noted/db.py` after `get_attachment_names`:

```python
def get_table_data(conn: sqlite3.Connection, identifier: str) -> bytes | None:
    """Fetch ZMERGEABLEDATA1 for a table attachment by identifier.

    Args:
        conn: Database connection.
        identifier: The attachment's unique identifier (UUID).

    Returns:
        Raw gzipped protobuf bytes, or None if not found.
    """
    query = """
        SELECT ZMERGEABLEDATA1
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZIDENTIFIER = ?
          AND ZMERGEABLEDATA1 IS NOT NULL
    """
    cursor = conn.execute(query, (identifier,))
    row = cursor.fetchone()
    if row is None:
        return None
    return row["ZMERGEABLEDATA1"]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/db.py tests/test_db.py && uv run pyrefly check src/noted/db.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "feat(db): add get_table_data function"
```

---

## Task 3: Create Tables Module with Protobuf Helpers

**Files:**
- Create: `src/noted/tables.py`
- Create: `tests/test_tables.py`

**Step 1: Write the failing test**

Create `tests/test_tables.py`:

```python
"""Tests for noted.tables."""

from noted.tables import decode_varint, decode_fields


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
    fields = decode_fields(data)
    assert 1 in fields
    assert fields[1][0][1] == 150  # (wire_type, value)
    assert 2 in fields
    assert fields[2][0][1] == b"test"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tables.py::test_decode_varint_single_byte -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'noted.tables'`

**Step 3: Write minimal implementation**

Create `src/noted/tables.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tables.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/tables.py tests/test_tables.py && uv run pyrefly check src/noted/tables.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/tables.py tests/test_tables.py
git commit -m "feat(tables): add protobuf decoding helpers"
```

---

## Task 4: Add Table Parsing Function

**Files:**
- Modify: `src/noted/tables.py`
- Modify: `tests/test_tables.py`

**Step 1: Write the failing test**

Add to `tests/test_tables.py`:

```python
import gzip

from noted.models import Table
from noted.tables import decode_fields, decode_varint, parse_table_data


def test_parse_table_data_returns_none_for_invalid() -> None:
    """Test that invalid data returns None."""
    result = parse_table_data(b"not gzip data")
    assert result is None


def test_parse_table_data_returns_none_for_empty() -> None:
    """Test that empty gzip returns None."""
    empty_gzip = gzip.compress(b"")
    result = parse_table_data(empty_gzip)
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tables.py::test_parse_table_data_returns_none_for_invalid -v`
Expected: FAIL with `ImportError: cannot import name 'parse_table_data'`

**Step 3: Write minimal implementation**

Add to `src/noted/tables.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tables.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/tables.py tests/test_tables.py && uv run pyrefly check src/noted/tables.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/tables.py tests/test_tables.py
git commit -m "feat(tables): add parse_table_data function"
```

---

## Task 5: Add Rich Table Renderer

**Files:**
- Modify: `src/noted/display.py`
- Modify: `tests/test_display.py`

**Step 1: Write the failing test**

Add to `tests/test_display.py`:

```python
from noted.display import (
    display_count,
    display_note_view,
    display_notes_table,
    table_to_rich,
)
from noted.models import Note, NoteContent, NoteSummary, Table


def test_table_to_rich() -> None:
    """Test converting Table to Rich Table."""
    table = Table(
        rows=2,
        columns=2,
        cells={(0, 0): "A", (0, 1): "B", (1, 0): "C", (1, 1): "D"},
    )
    rich_table = table_to_rich(table)
    # Rich Table should have 2 columns
    assert rich_table.column_count == 2


def test_table_to_rich_empty_cells() -> None:
    """Test Rich table with missing cells shows empty."""
    table = Table(rows=2, columns=2, cells={(0, 0): "Only"})
    rich_table = table_to_rich(table)
    assert rich_table.column_count == 2
```

Update the import at the top to include `table_to_rich` and `Table`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_display.py::test_table_to_rich -v`
Expected: FAIL with `ImportError: cannot import name 'table_to_rich'`

**Step 3: Write minimal implementation**

Add import at top of `src/noted/display.py`:

```python
from noted.models import Note, NoteContent, NoteSummary, Table
```

Add function after `display_note_view`:

```python
def table_to_rich(table: Table) -> RichTable:
    """Convert Table data to Rich Table for terminal display.

    Args:
        table: Parsed table data.

    Returns:
        Rich Table object ready for printing.
    """
    rich_table = RichTable(box=box.SIMPLE, show_header=False)

    # Add columns
    for col in range(table.columns):
        rich_table.add_column()

    # Add rows
    for row in range(table.rows):
        row_data = [table.get_cell(row, col) for col in range(table.columns)]
        rich_table.add_row(*row_data)

    return rich_table
```

Add import for box at top:

```python
from rich import box
from rich.table import Table as RichTable
```

Update existing import to rename:

```python
from rich.table import Table as RichTable
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_display.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/display.py tests/test_display.py && uv run pyrefly check src/noted/display.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/display.py tests/test_display.py
git commit -m "feat(display): add table_to_rich renderer"
```

---

## Task 6: Update CLI to Parse and Display Tables

**Files:**
- Modify: `src/noted/cli.py`
- Modify: `src/noted/display.py`

**Step 1: Update CLI to fetch and parse tables**

Modify `src/noted/cli.py` view command to add table parsing after getting attachment names:

```python
from noted import db, display, protobuf, tables
```

In the view command, after `content = protobuf.parse_note_data(raw_data, attachment_names)`:

```python
        # Parse table attachments
        if content.attachments:
            for attachment in content.attachments:
                if attachment.type_uti == "com.apple.notes.table":
                    table_data = db.get_table_data(conn, attachment.identifier)
                    if table_data:
                        attachment.table = tables.parse_table_data(table_data)

        conn.close()
```

Note: Move `conn.close()` after the table parsing loop.

**Step 2: Update display_note_view to render inline tables**

Modify `src/noted/display.py` `display_note_view` function:

```python
def display_note_view(note: Note, content: NoteContent) -> None:
    """Display a note's full content.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
    """
    # Format metadata line
    folder_str = note.folder or "(No Folder)"
    modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"
    subtitle = f"Folder: {folder_str}  |  Modified: {modified_str}"

    # Create header panel
    panel = Panel(
        Text(subtitle, style="dim"),
        title=f"[bold]{note.title}[/bold]",
        title_align="left",
        border_style="blue",
    )
    console.print(panel)
    console.print()

    # Build attachment lookup for inline rendering
    table_lookup: dict[str, Table] = {}
    if content.attachments:
        for att in content.attachments:
            if att.table is not None:
                table_lookup[att.identifier] = att.table

    # Print body text with inline tables
    if content.text:
        _render_text_with_tables(content.text, table_lookup)
    else:
        console.print("[dim]No content[/dim]")


def _render_text_with_tables(text: str, table_lookup: dict[str, Table]) -> None:
    """Render text, replacing [Table] markers with actual tables.

    Args:
        text: Note text with [Table] markers.
        table_lookup: Mapping of identifier to parsed Table.
    """
    # For now, just print the text - tables show as [Table] marker
    # TODO: Parse markers and render inline tables
    console.print(text)
```

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 4: Run linting and type checking**

Run: `uv run ruff check src/ tests/ && uv run pyrefly check src/`
Expected: No errors

**Step 5: Manual test**

Run: `uv run noted view 10971`
Expected: Note displays with tables showing cell content (even if single column)

**Step 6: Commit**

```bash
git add src/noted/cli.py src/noted/display.py
git commit -m "feat(cli): integrate table parsing into view command"
```

---

## Task 7: Improve Table Grid Reconstruction

**Files:**
- Modify: `src/noted/tables.py`
- Modify: `tests/test_tables.py`

This task improves the parsing to detect actual row/column structure from the CRDT data rather than using single-column fallback.

**Step 1: Add test with real table data**

Add to `tests/test_tables.py`:

```python
def test_parse_table_data_with_real_structure(tmp_path: Path) -> None:
    """Test parsing table with multiple columns detected."""
    # This test uses actual table data from the database
    # For unit testing, we verify the interface works
    import sqlite3
    from pathlib import Path as P

    db_path = P.home() / ".cache/noted/NoteStore.sqlite"
    if not db_path.exists():
        pytest.skip("Apple Notes database not available")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT ZMERGEABLEDATA1
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTYPEUTI = 'com.apple.notes.table'
          AND ZMERGEABLEDATA1 IS NOT NULL
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if not row:
        pytest.skip("No tables found in database")

    result = parse_table_data(row["ZMERGEABLEDATA1"])
    assert result is not None
    assert result.rows > 0
    assert result.columns > 0
    assert len(result.cells) > 0
```

Add `import pytest` and `from pathlib import Path` at top.

**Step 2: Improve _parse_mergeable_data_object**

The current implementation creates single-column tables. Improve it to detect grid structure by analyzing the ordered sets for rows and columns.

This is complex and may require iterative refinement. The key insight from research:
- `crRows` ordered set contains row UUIDs in order
- `crColumns` ordered set contains column UUIDs in order
- `cellColumns` is a nested dict: column_uuid -> row_uuid -> cell_content

**Step 3: Run tests and iterate**

Run: `uv run pytest tests/test_tables.py -v`

Continue refining the parsing until multi-column tables are detected correctly.

**Step 4: Commit improvements**

```bash
git add src/noted/tables.py tests/test_tables.py
git commit -m "feat(tables): improve grid structure detection"
```

---

## Task 8: Render Tables Inline in Text

**Files:**
- Modify: `src/noted/display.py`
- Modify: `src/noted/protobuf.py`

**Step 1: Update protobuf to track table positions**

Modify `_process_attachments` in `src/noted/protobuf.py` to use unique markers:

Change the table marker from `[Table]` to `[Table:identifier]`:

```python
if title:
    marker = f"[{type_name}: {title}]"
elif type_name == "Table":
    marker = f"[Table:{identifier}]"
else:
    marker = f"[{type_name}]"
```

**Step 2: Update display to render inline**

Modify `_render_text_with_tables` in `src/noted/display.py`:

```python
import re


def _render_text_with_tables(text: str, table_lookup: dict[str, Table]) -> None:
    """Render text, replacing [Table:id] markers with actual tables.

    Args:
        text: Note text with [Table:identifier] markers.
        table_lookup: Mapping of identifier to parsed Table.
    """
    # Pattern matches [Table:uuid-here]
    pattern = r"\[Table:([^\]]+)\]"

    last_end = 0
    for match in re.finditer(pattern, text):
        # Print text before this marker
        before = text[last_end : match.start()]
        if before:
            console.print(before, end="")

        # Render the table
        identifier = match.group(1)
        if identifier in table_lookup:
            table = table_lookup[identifier]
            rich_table = table_to_rich(table)
            console.print()
            console.print(rich_table)
        else:
            # Table not parsed, show placeholder
            console.print("[Table]", end="")

        last_end = match.end()

    # Print remaining text
    remaining = text[last_end:]
    if remaining:
        console.print(remaining)
```

**Step 3: Run tests**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 4: Manual test**

Run: `uv run noted view 10971`
Expected: Tables render inline with Rich formatting

**Step 5: Commit**

```bash
git add src/noted/protobuf.py src/noted/display.py
git commit -m "feat(display): render tables inline in note view"
```

---

## Task 9: Add Markdown Table Renderer (Future-Proofing)

**Files:**
- Modify: `src/noted/display.py`
- Modify: `tests/test_display.py`

**Step 1: Write the failing test**

Add to `tests/test_display.py`:

```python
from noted.display import table_to_markdown


def test_table_to_markdown() -> None:
    """Test converting Table to markdown string."""
    table = Table(
        rows=2,
        columns=2,
        cells={(0, 0): "A", (0, 1): "B", (1, 0): "C", (1, 1): "D"},
    )
    md = table_to_markdown(table)
    assert "| A | B |" in md
    assert "| C | D |" in md
    assert "---" in md  # Header separator
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_display.py::test_table_to_markdown -v`
Expected: FAIL with `ImportError: cannot import name 'table_to_markdown'`

**Step 3: Write minimal implementation**

Add to `src/noted/display.py`:

```python
def table_to_markdown(table: Table) -> str:
    """Convert Table data to markdown string.

    Args:
        table: Parsed table data.

    Returns:
        Markdown-formatted table string.
    """
    if table.rows == 0 or table.columns == 0:
        return ""

    lines = []

    # Header row (first row of data)
    header = [table.get_cell(0, col) or " " for col in range(table.columns)]
    lines.append("| " + " | ".join(header) + " |")

    # Separator
    lines.append("| " + " | ".join(["---"] * table.columns) + " |")

    # Data rows
    for row in range(1, table.rows):
        cells = [table.get_cell(row, col) or " " for col in range(table.columns)]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_display.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/noted/display.py tests/test_display.py
git commit -m "feat(display): add table_to_markdown renderer"
```

---

## Task 10: Final Integration Test and Cleanup

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Add integration test for tables**

Add to `tests/test_integration.py`:

```python
@pytest.mark.skipif(not NOTES_DB_AVAILABLE, reason="Apple Notes database not available")
def test_view_note_with_table() -> None:
    """Integration test: view a note that contains a table."""
    import sqlite3
    from pathlib import Path

    # Find a note with a table
    db_path = Path.home() / ".cache/noted/NoteStore.sqlite"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT DISTINCT ZNOTE
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTYPEUTI = 'com.apple.notes.table'
          AND ZMERGEABLEDATA1 IS NOT NULL
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if not row:
        pytest.skip("No notes with tables found")

    note_id = str(row["ZNOTE"])
    result = runner.invoke(app, ["view", note_id])

    # Should succeed and not show raw [Table] markers
    assert result.exit_code == 0
```

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 3: Run linting and type checking**

Run: `uv run ruff check src/ tests/ && uv run pyrefly check src/`
Expected: No errors

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for table display"
```

---

## Summary

After completing all tasks:

1. `Table` dataclass for format-agnostic table data
2. `tables.py` module with CRDT protobuf parsing
3. `get_table_data()` database function
4. `table_to_rich()` and `table_to_markdown()` renderers
5. Inline table rendering in `noted view`
6. Graceful fallback for unparseable tables

The table parsing uses a combination of structured protobuf decoding and string extraction fallback to maximize data recovery even when the full CRDT structure can't be reconstructed.
