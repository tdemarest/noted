# Apple Notes CRDT Table Structure

> Canonical overview: [apple-notes-storage-reference.md](./apple-notes-storage-reference.md) (Q5, "How a table is stored"). This deep-dive adds protobuf field numbers, the decoding steps implemented in `src/noted/tables.py`, and wire-type notes.

## Storage

A table is an attachment row with UTI `com.apple.notes.table`. Its content is gzip-compressed `MergableDataProto` in `ZMERGEABLEDATA1`. The data is a CRDT object graph, not a grid: cells are keyed by row and column ids, and display order is a separate ordered set. Row count, column count and order come from the graph, never from heuristics.

## Protobuf layout

```
ZMERGEABLEDATA1 (gzip)
  MergableDataProto
    field 2: MergableDataObject wrapper
      field 3: data
        field 3  entries[]   objects, addressed by index (ObjectID.object_index)
        field 4  keys[]      identity, crRows, crColumns, cellColumns,
                             crTableColumnDirection, UUIDIndex, self
        field 5  types[]     com.apple.notes.ICTable, com.apple.CRDT.NSUUID,
                             com.apple.CRDT.NSString, ...
        field 6  uuids[]     row and column ids as 16 raw bytes
```

Map keys are indexes into `keys[]`; resolve them by name (as `tables.py` does) rather than assuming fixed positions.

Object shapes:

```
UUID object   = custom map { UUIDIndex -> n }        meaning uuids[n]
ICTable       = custom map { crRows, crColumns, cellColumns,
                             crTableColumnDirection, identity }
crRows / crColumns -> OrderedSet
    ordering.array.attachment[i].uuid   slot id at display position i
    ordering.contents { slot -> id }    row or column id that cells use
cellColumns   -> Dictionary { column id -> Dictionary { row id -> cell } }
cell          -> entry holding a nested Note (note_text + attribute_run)
crTableColumnDirection -> NSString "CRTableColumnDirectionLeftToRight"
```

Each cell is a small note with its own formatting, decoded like a note body.

## Decoding steps

1. gunzip `ZMERGEABLEDATA1` and parse `MergableDataProto`.
2. Find the `ICTable` entry and read its `crRows`, `crColumns` and `cellColumns` references.
3. For rows and columns separately, walk `ordering.array` in order. For each slot, map it through `ordering.contents` to the row or column id. This yields the display-ordered id lists.
4. For display position (r, c): look up `cellColumns[column id][row id]`.
5. Decode the cell's nested Note to text.

Rules:

- A missing cell entry is an empty cell (never typed in).
- Slot mappings whose slot is no longer in the ordering array belong to removed rows or columns; ignore them.
- Cells never reference slot ids directly. The extra indirection lets one device reorder rows and columns while another edits cells.
- Column direction was left to right in every table observed.

## Why it is not column-major text

Older notes on this format described cells as a flat list stored column by column, with headers at the end of each column, and recovered display order from the `ZSUMMARY` column. That is not how the data is organised. Order lives in `crRows` and `crColumns`, any row can be a header, and `ZSUMMARY` (a search summary of the cell text) is not used for layout. Do not detect tables by header names or infer dimensions from `ZSUMMARY`.

## Wire types

| Wire type | Name | Used for |
|-----------|------|----------|
| 0 | Varint | ints, bools, enums |
| 1 | 64-bit | fixed64, double |
| 2 | Length-delimited | strings, bytes, nested messages, packed fields |
| 5 | 32-bit | fixed32, float |

Wire types 3, 4, 6 and 7 are deprecated or reserved; a decoder should stop or skip.

## Known gaps

- Tables whose attachment row has no `ZMERGEABLEDATA1` yet (never synced) cannot be decoded.
- Placeholders with no attachment row at all (for example tables lost in an Evernote import) show as blank in Notes and cannot be recovered; see Q2 in the reference.
- Merged cells: not known to exist.
