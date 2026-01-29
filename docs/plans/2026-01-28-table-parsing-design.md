# Design: Apple Notes Table Parsing

## Overview

Parse and display Apple Notes embedded tables inline in `noted view` output. Tables are stored as gzipped CRDT protobufs in `ZMERGEABLEDATA1` and require complex reconstruction from ordered sets and nested dictionaries.

## Goals

- Display tables inline where they appear in the note
- Use Rich tables for terminal display (consistent with existing output)
- Parse into format-agnostic data structure for future markdown/HTML export
- Handle partial/corrupted data gracefully

## Data Model

### New Models in `models.py`

```python
@dataclass
class TableCell:
    """A single cell in a table."""
    row: int
    column: int
    text: str


@dataclass
class Table:
    """Parsed table from Apple Notes.

    Stores data in a neutral format that can be rendered
    as Rich, markdown, ASCII, or HTML.
    """
    rows: int
    columns: int
    cells: dict[tuple[int, int], str]  # (row, col) -> text

    def get_cell(self, row: int, col: int) -> str:
        """Get cell content, empty string if not present."""
        return self.cells.get((row, col), "")
```

### Update `Attachment` Model

```python
@dataclass
class Attachment:
    identifier: str
    type_uti: str
    title: str | None = None
    table: Table | None = None  # Populated for table attachments
```

## Parsing Architecture

### New Module: `src/noted/tables.py`

Handles CRDT table protobuf parsing:

```python
def parse_table_data(data: bytes) -> Table | None:
    """Parse gzipped CRDT table protobuf from ZMERGEABLEDATA1.

    Returns Table with extracted cells, or None if parsing fails completely.
    Partially parsed tables return with available cells.
    """
```

### CRDT Table Structure

The table protobuf contains:

- **Field 3 (Table Objects)**: Actual data structures
- **Field 4 (Key Items)**: Maps indices to property names (`crRows`, `crColumns`, `cellColumns`)
- **Field 5 (Type Items)**: Maps indices to CRDT types
- **Field 6 (UUID Items)**: 16-byte identifiers for rows/columns/cells

### Parsing Steps

1. Decompress gzip data
2. Parse outer protobuf to extract key items, UUID items, table objects
3. Build row ordering from `crRows` ordered set
4. Build column ordering from `crColumns` ordered set
5. Extract cell content from `cellColumns` nested dictionaries
6. Reconstruct grid using UUID-to-position mappings

### Database Function

```python
def get_table_data(conn: Connection, identifier: str) -> bytes | None:
    """Fetch ZMERGEABLEDATA1 for a table attachment by identifier."""
```

## Display Architecture

### Modular Renderers

The `Table` dataclass is format-agnostic. Separate renderer functions for each output format:

```python
def table_to_rich(table: Table) -> RichTable:
    """Render table as Rich Table for terminal."""

def table_to_markdown(table: Table) -> str:
    """Render table as markdown string."""

def table_to_ascii(table: Table) -> str:
    """Render table as ASCII grid."""

def table_to_html(table: Table) -> str:
    """Render table as HTML <table> element."""
```

### Inline Rendering

Update `display_note_view()` to:
1. Process text with attachment markers
2. When encountering a table attachment with parsed `Table` data, render inline
3. Use appropriate renderer based on output format

### Future CLI Options

```bash
noted view 123                    # Default: Rich tables
noted view 123 --format markdown  # Markdown output
noted export 123 --format html    # HTML export
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Gzip decompression fails | Return `None`, display `[Table: corrupted]` |
| Protobuf parsing fails | Return `None`, display `[Table: unknown format]` |
| Missing row/column UUIDs | Include parsed cells, leave gaps empty |
| Cell content missing | Empty string (normal for sparse tables) |

Use loguru DEBUG logging for parsing failures.

## File Changes

| File | Change |
|------|--------|
| `src/noted/tables.py` | NEW: CRDT table parsing |
| `src/noted/models.py` | Add `Table`, `TableCell`, update `Attachment` |
| `src/noted/db.py` | Add `get_table_data()` |
| `src/noted/display.py` | Add `table_to_rich()`, update `display_note_view()` |
| `src/noted/cli.py` | Fetch and parse tables in view command |

## Data Flow

```
CLI view command
  → db.get_note_content()
  → protobuf.parse_note_data() → NoteContent with attachments
  → for each table attachment:
      → db.get_table_data(identifier)
      → tables.parse_table_data() → Table object
      → store in Attachment.table
  → display.display_note_view()
      → render text segments
      → call table_to_rich() for inline tables
```

## References

- [Ciofeca Forensics - Embedded Tables](https://www.ciofecaforensics.com/2020/01/14/apple-notes-revisited-embedded-tables/)
- [apple_cloud_notes_parser](https://github.com/threeplanetssoftware/apple_cloud_notes_parser)
- [dunhamsteve/notesutils](https://github.com/dunhamsteve/notesutils/blob/master/notes.md)
