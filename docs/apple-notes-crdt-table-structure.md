# Apple Notes CRDT Table Structure

This document describes the internal structure of Apple Notes tables as stored in the `ZMERGEABLEDATA1` column of `ZICCLOUDSYNCINGOBJECT`. This information was reverse-engineered through analysis of actual table data.

## Overview

Apple Notes tables are stored as **gzip-compressed protobufs** using a **CRDT (Conflict-free Replicated Data Type)** format. The CRDT design allows tables to be synchronized across devices while handling concurrent edits.

Key characteristics:
- Tables are embedded as attachments with UTI `com.apple.notes.table`
- Cell data is stored **column-by-column**, not row-by-row
- Headers appear at the **end** of each column's cell range
- The storage order of columns may differ from display order (SOLVED via ZSUMMARY)
- The storage order of rows may differ from display order (SOLVED via ZSUMMARY)
- ZSUMMARY contains all cell values in **row-major display order**, enabling dimension inference for tables with non-standard headers

## Protobuf Structure Hierarchy

```
ZMERGEABLEDATA1 (gzip compressed)
└── MergableDataProto (root)
    └── field 2: Inner wrapper
        └── field 3: MergableDataObject
            ├── field 3: table_object entries (repeated) ← Cell data here
            ├── field 4: key_item (repeated) ← Property names
            ├── field 5: type_item (repeated) ← CRDT type names
            ├── field 6: uuid_item (repeated) ← Row/column UUIDs
            └── field 7: (additional metadata)
```

## Key Fields in MergableDataObject

### Field 4: key_item (Property Names)

Contains string identifiers for CRDT properties:

| Index | Key Name | Purpose |
|-------|----------|---------|
| 0 | `identity` | Object identity |
| 1 | `crColumns` | Column ordered set |
| 2 | `UUIDIndex` | UUID indexing |
| 3 | `crRows` | Row ordered set |
| 4 | `crTableColumnDirection` | Text direction (LTR/RTL) |
| 5 | `self` | Self-reference |
| 6 | `cellColumns` | Cell-to-column mapping |

### Field 6: uuid_item (UUIDs)

Contains 16-byte UUIDs that identify rows and columns. The count typically equals `num_rows + num_columns + additional_metadata`.

Example: A 5-column × 15-row table had 69 UUIDs.

### Field 3: table_object Entries

This is the most important field - it contains the actual table data. Entries have different structures based on their field numbers:

| Entry Type | Field Number | Count (example) | Content |
|------------|--------------|-----------------|---------|
| Metadata | 13 | 76 | Column/row definitions, CRDT metadata |
| Cell containers | 16 | 2 | Nested cell structures |
| **Cell values** | **10** | **75** | **Actual cell text content** |
| Ordered sets | 6 | 6 | Row/column ordering |
| Root | 1 | 1 | Table root object |

## Cell Storage Structure (Field 10 Entries)

Cell text is stored in **field 10** entries within `table_object`. Each field 10 entry has this structure:

```
table_object entry
└── field 10: Cell container
    ├── field 2: Cell text (UTF-8 string) ← THE ACTUAL CONTENT
    ├── field 3: Cell metadata (nested)
    │   ├── field 2: (integer)
    │   └── field 5: (integer)
    └── field 5: Timestamp/ordering info (nested)
        ├── field 1: (integer, possibly column index)
        └── field 13: (timestamp, e.g., 1765301875)
```

### Example Cell Extraction

```python
for entry_data in obj[3]:  # table_object entries
    entry = decode_fields(entry_data)
    if 10 in entry:  # This is a cell entry
        f10 = decode_fields(entry[10][0][1])
        if 2 in f10:
            text = f10[2][0][1].decode('utf-8')
            # text contains the cell value
```

## Column-Major Storage Order

**Critical insight**: Cells are stored column-by-column, not row-by-row.

For a table with 5 columns and 15 rows (75 cells total):

```
Storage order:
┌─────────────────────────────────────────────────────────────────────┐
│ Column 0 data    │ Column 1 data    │ ... │ Column 4 data          │
│ (cells 0-13)     │ (cells 15-28)    │     │ (cells 60-73)          │
│ + header (14)    │ + header (29)    │     │ + header (74)          │
└─────────────────────────────────────────────────────────────────────┘

Cell indices:
- Column 0: cells 0-14 (14 data rows + 1 header at position 14)
- Column 1: cells 15-29 (14 data rows + 1 header at position 29)
- Column 2: cells 30-44 (14 data rows + 1 header at position 44)
- Column 3: cells 45-59 (14 data rows + 1 header at position 59)
- Column 4: cells 60-74 (14 data rows + 1 header at position 74)
```

### Header Position Pattern

Headers are at the **end** of each column's cell range:
- `header_position = (column_index + 1) * cells_per_column - 1`

Or equivalently, for 5 columns with 15 cells each:
- Column 0 header: position 14
- Column 1 header: position 29
- Column 2 header: position 44
- Column 3 header: position 59
- Column 4 header: position 74

## Storage Order vs Display Order

**Important**: Both **columns** and **rows** in ZMERGEABLEDATA1 may have a storage order that differs from the display order.

### Column Display Order (SOLVED)

The storage order of columns may differ from display order.

Example from note 12345:

| Storage Order | Header | Display Order | Header |
|---------------|--------|---------------|--------|
| 0 | Date | 0 | Date |
| 1 | Performed By | 1 | Miles |
| 2 | Cost | 2 | Cost |
| 3 | Service Desc | 3 | Performed By |
| 4 | Miles | 4 | Service Desc |

**Solution**: The `ZSUMMARY` column in `ZICCLOUDSYNCINGOBJECT` contains the column headers in **display order**, separated by newlines.

```sql
SELECT ZSUMMARY FROM ZICCLOUDSYNCINGOBJECT
WHERE ZTYPEUTI = 'com.apple.notes.table' AND ZNOTE = 12345;

-- Result: "Date\nMiles\nCost\nPerformed By\nService Desc\n2025-12-..."
```

The first N lines of ZSUMMARY (where N = number of columns) are the headers in display order.

### Row Display Order (SOLVED)

**Key discovery**: ZSUMMARY contains ALL table cell values in display order, not just headers!

The ZSUMMARY structure is:
- First N lines: Column headers in display order
- Remaining lines: Cell values, N values per row, in display order

This allows us to determine row display order by matching first-column values from ZSUMMARY against storage row values.

**Algorithm**:
1. Extract first-column values from ZSUMMARY in the order they appear
2. For each first-column value, find the matching storage row
3. For duplicate first-column values (e.g., two rows with same date), use secondary columns (columns 2 and 3) to disambiguate
4. Reorder storage rows to match ZSUMMARY order

Example from note 12345 - the two 2023-02-18 rows are distinguished by their Cost column:
- First in ZSUMMARY: 2023-02-18 with empty Cost (window issue)
- Second in ZSUMMARY: 2023-02-18 with Cost="$235..." (tire issue)

### Column Reordering Algorithm (Implemented)

```python
def reorder_columns(table: Table, summary: str) -> Table:
    # Extract display order from ZSUMMARY
    display_headers = summary.split("\n")[:table.columns]

    # Get storage order from row 0
    storage_headers = [table.get_cell(0, col) for col in range(table.columns)]

    # Build mapping: display_col -> storage_col
    col_mapping = []
    for display_header in display_headers:
        for storage_col, storage_header in enumerate(storage_headers):
            if storage_header == display_header:
                col_mapping.append(storage_col)
                break

    # Reorder cells using mapping
    new_cells = {}
    for row in range(table.rows):
        for display_col, storage_col in enumerate(col_mapping):
            new_cells[(row, display_col)] = table.get_cell(row, storage_col)

    return Table(rows=table.rows, columns=table.columns, cells=new_cells)
```

## Sample Table Data

From note 12345 (Vehicle Service Record):

### CLI Output (Now Matches Apple Notes Display Order)

Both column and row ordering are now correct:

| Date | Miles | Cost | Performed By | Service Desc |
|------|-------|------|--------------|--------------|
| 2025-12-09 | 14-- | $0.00 | Quick Tire Shop | Driver rear tire low again (25 psi). Check and filled at Downtown. |
| 2025-11-22 | 14— | $259.61 | Self | Napa Optma Redtop Battery BAT N9935RED |
| 2025-10-08 | 14— | $0.00 | Quick Tire Shop | Right rear tire check low. Replaced valve |
| 2025-06-09 | 11862 | $265.76 | Main Street Auto | 12k service (intermediate). Next, 18k, Dec 2025. |
| 2025-06-02 | 11828 | $1430.04 | Quick Tire Shop | New tires - all-season tires (4). Install 2025-06-04 |
| 2024-10-28 | | $90 | Myself | New wipers: Driver: PIAA 95065 Super Silicone Wiper Blade - 26"... |
| 2023-10-13 | 9324 | $373 | Main Street Auto | 12k mileage service (basic). Oil, tire rotation, inspection... |
| 2023-02-18 | 8829 | | | Driver window control panel - passenger window operation doesn't work... |
| 2023-02-18 | 8829 | $235 tire + $24+$1.70+ $3, $35 tire certificate | Quick Tire Shop | Passenger Rear tire had a sidewall tear... |
| 2023-02-03 | 8065 | $201 | Main Street Auto | 9k service (basic), scheduled maintenance |
| 2022-05-09 | 6999 | $5 | Self | Both key fob batteries replaced CR2032 |
| 2020-03-11 | 6015 | $200.69 | Main Street Auto | 6K Maintenance (Regular Interval) |
| 2019-05-30 | 3761 | $89.95 | Quick Lube | Oil change - Quick Lube |
| 2019-01-11 | 1500 | $54.95 | Self | New wipers: Driver: PIAA 95065 Super Silicone Wiper Blade... |

**Note**: Duplicate rows (e.g., two 2023-02-18 entries) are distinguished by comparing additional columns (Cost, Performed By) against ZSUMMARY values.

## Parsing Algorithm

The parser uses two strategies to determine table dimensions:

### Strategy 1: Known Header Detection

For tables with common headers (Date, Miles, Cost, Name, etc.), the parser detects headers at the end of each column's cell range:

```python
def parse_table(obj_data: bytes) -> Table:
    obj = decode_fields(obj_data)

    # 1. Extract all cells from field 10 entries
    cells = []
    for entry_data in obj[3]:  # table_object entries
        entry = decode_fields(entry_data)
        if 10 in entry:
            f10 = decode_fields(entry[10][0][1])
            if 2 in f10:
                text = f10[2][0][1].decode('utf-8')
                cells.append(text)

    # 2. Find headers to determine column count
    known_headers = {"Date", "Miles", "Cost", "Performed By", "Service Desc", ...}
    header_positions = [(i, val) for i, val in enumerate(cells) if val in known_headers]
    num_cols = len(header_positions)

    # 3. Calculate cells per column
    cells_per_col = header_positions[0][0] + 1  # First header position + 1
    num_rows = cells_per_col

    # 4. Reconstruct grid (headers at row 0, data in rows 1+)
    grid = {}
    for col in range(num_cols):
        col_start = col * cells_per_col
        col_end = col_start + cells_per_col
        grid[(0, col)] = cells[col_end - 1]  # Header
        for i, cell_idx in enumerate(range(col_start, col_end - 1)):
            grid[(i + 1, col)] = cells[cell_idx]  # Data

    return Table(rows=num_rows, columns=num_cols, cells=grid)
```

### Strategy 2: ZSUMMARY-Based Dimension Inference

When headers aren't in the known set (e.g., "Feature", "Shortcut"), the parser falls back to using ZSUMMARY to infer dimensions:

```python
def infer_dimensions_from_summary(cell_values: list[str], summary: str) -> Table:
    # ZSUMMARY contains data in row-major display order
    summary_lines = [line.strip() for line in summary.split("\n") if line.strip()]
    num_values = len(summary_lines)

    # Try common column counts that divide evenly
    for num_cols in [2, 3, 4, 5]:
        if num_values % num_cols == 0:
            num_rows = num_values // num_cols

            # Verify summary values match extracted cells
            if set(summary_lines) & set(cell_values):
                # Build grid directly from summary (row-major order)
                grid = {}
                for i, val in enumerate(summary_lines):
                    row = i // num_cols
                    col = i % num_cols
                    grid[(row, col)] = val
                return Table(rows=num_rows, columns=num_cols, cells=grid)

    # Final fallback: single column
    return Table(rows=len(cell_values), columns=1,
                 cells={(i, 0): v for i, v in enumerate(cell_values)})
```

**Example**: A table with headers "Feature" and "Shortcut":

```
ZSUMMARY: "Feature\nShortcut\nBold\nCmd + B\nItalic\nCmd + I\nHeading\nShift + Cmd + H\n"

8 values ÷ 2 columns = 4 rows

Result:
| Feature | Shortcut       |
|---------|----------------|
| Bold    | Cmd + B        |
| Italic  | Cmd + I        |
| Heading | Shift + Cmd + H|
```

## CRDT Noise Filtering

The protobuf contains many CRDT metadata strings that should be filtered out:

```python
CRDT_NOISE = {
    "identity", "cellColumns", "UUIDIndex", "crRows",
    "crTableColumnDirection", "self", "crColumns",
    "CRTableColumnDirectionLeftToRight",
}

CRDT_SUBSTRINGS = ("CRDT", "CRTable", "LeftToRight", "00000000-0000-0000")
```

Also filter:
- Strings starting with `com.apple.`
- Very short strings (≤3 characters)
- Strings with high non-alphanumeric ratio

## Wire Type Reference

Protobuf wire types used in Apple Notes:

| Wire Type | Name | Description |
|-----------|------|-------------|
| 0 | Varint | int32, int64, uint32, uint64, sint32, sint64, bool, enum |
| 1 | 64-bit | fixed64, sfixed64, double |
| 2 | Length-delimited | string, bytes, embedded messages, packed repeated fields |
| 5 | 32-bit | fixed32, sfixed32, float |

Wire types 3, 4, 6, 7 are deprecated/reserved and should be skipped.

## Future Work

1. ~~**Column ordering**: Parse `crColumns` ordered set to determine correct display order~~ **SOLVED**: Use ZSUMMARY column for display order
2. ~~**Row ordering**: Parse `crRows` ordered set for row display order~~ **SOLVED**: Use ZSUMMARY cell values to match and reorder rows
3. ~~**Dimension inference for unknown headers**: Tables with non-standard headers failed to parse correctly~~ **SOLVED**: Use ZSUMMARY to infer dimensions when header detection fails
4. **Empty cells**: Handle cells with no content (currently show as empty string)
5. **Rich text**: Parse formatting within cells (bold, italic, links)
6. **Merged cells**: Investigate if Apple Notes supports cell merging

## References

- Apple Notes database location: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- Table attachments: `ZICCLOUDSYNCINGOBJECT` where `ZTYPEUTI = 'com.apple.notes.table'`
- Table data: `ZMERGEABLEDATA1` column (gzip-compressed protobuf)
