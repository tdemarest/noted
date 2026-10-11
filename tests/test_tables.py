"""Tests for noted.tables."""

import gzip
import sqlite3
from pathlib import Path

import pytest

from noted.protobuf import Note
from noted.tables import (
    CustomMap,
    Dictionary,
    DictionaryElement,
    MapEntry,
    MergableDataObject,
    MergableDataProto,
    MergeableDataObjectData,
    MergeableDataObjectEntry,
    ObjectId,
    OrderedSet,
    OrderedSetOrdering,
    OrderedSetOrderingArray,
    OrderedSetOrderingArrayAttachment,
    parse_table_data,
)

KEYS = ["identity", "crRows", "crColumns", "cellColumns", "crTableColumnDirection", "UUIDIndex"]
TYPES = ["com.apple.notes.ICTable", "com.apple.CRDT.NSUUID"]


def uid(n: int) -> bytes:
    """Return a synthetic 16-byte UUID for a small integer."""
    return bytes([n]) * 16


class TableBuilder:
    """Builds a synthetic gzipped MergableDataProto table by hand."""

    def __init__(self) -> None:
        """Start with an empty object graph."""
        self.entries: list[MergeableDataObjectEntry] = []
        self.uuids: list[bytes] = []

    def add(self, entry: MergeableDataObjectEntry) -> ObjectId:
        """Append an entry and return a reference to it."""
        self.entries.append(entry)
        return ObjectId(object_index=len(self.entries) - 1)

    def uuid_ref(self, value: bytes) -> ObjectId:
        """Add a UUID object for value and return a reference to it."""
        if value not in self.uuids:
            self.uuids.append(value)
        index = ObjectId(unsigned_integer_value=self.uuids.index(value))
        cm = CustomMap(type=TYPES.index("com.apple.CRDT.NSUUID"))
        cm.map_entry = [MapEntry(key=KEYS.index("UUIDIndex"), value=index)]
        return self.add(MergeableDataObjectEntry(custom_map=cm))

    def ordered_set(self, order: list[bytes], contents: dict[bytes, bytes]) -> ObjectId:
        """Add an OrderedSet with slot display order and slot -> id contents."""
        array = OrderedSetOrderingArray(
            attachment=[
                OrderedSetOrderingArrayAttachment(index=i, uuid=slot)
                for i, slot in enumerate(order)
            ]
        )
        mapping = Dictionary(
            element=[
                DictionaryElement(key=self.uuid_ref(slot), value=self.uuid_ref(target))
                for slot, target in contents.items()
            ]
        )
        ordering = OrderedSetOrdering(array=array, contents=mapping)
        return self.add(MergeableDataObjectEntry(ordered_set=OrderedSet(ordering=ordering)))

    def cell_columns(self, cells: dict[tuple[bytes, bytes], str]) -> ObjectId:
        """Add the cellColumns dictionary from {(column id, row id): text}."""
        by_column: dict[bytes, list[DictionaryElement]] = {}
        for (col_id, row_id), text in cells.items():
            cell = self.add(MergeableDataObjectEntry(note=Note(note_text=text)))
            by_column.setdefault(col_id, []).append(
                DictionaryElement(key=self.uuid_ref(row_id), value=cell)
            )
        outer = []
        for col_id, elements in by_column.items():
            inner = self.add(MergeableDataObjectEntry(dictionary=Dictionary(element=elements)))
            outer.append(DictionaryElement(key=self.uuid_ref(col_id), value=inner))
        return self.add(MergeableDataObjectEntry(dictionary=Dictionary(element=outer)))

    def build(
        self, rows: ObjectId, columns: ObjectId, cells: ObjectId, table_type: int = 0
    ) -> bytes:
        """Add the ICTable map and return the gzipped proto bytes."""
        table = CustomMap(type=table_type)
        table.map_entry = [
            MapEntry(key=KEYS.index("crRows"), value=rows),
            MapEntry(key=KEYS.index("crColumns"), value=columns),
            MapEntry(key=KEYS.index("cellColumns"), value=cells),
        ]
        self.add(MergeableDataObjectEntry(custom_map=table))
        data = MergeableDataObjectData(
            entries=self.entries, keys=KEYS, types=TYPES, uuids=self.uuids
        )
        proto = MergableDataProto(mergable_data_object=MergableDataObject(version=1, data=data))
        return gzip.compress(bytes(proto))


# Row ids R1, R2 and column ids C1 (letter "a"), C2 (letter "b"); slots are separate ids.
R1, R2, R_OLD = uid(1), uid(2), uid(3)
C1, C2 = uid(11), uid(12)
RS1, RS2, RS_OLD = uid(21), uid(22), uid(23)
CS1, CS2 = uid(31), uid(32)
ALL_CELLS = {(C1, R1): "a1", (C1, R2): "a2", (C2, R1): "b1", (C2, R2): "b2"}


def build_two_by_two(
    cells: dict[tuple[bytes, bytes], str], extra_row_contents: dict[bytes, bytes] | None = None
) -> bytes:
    """Build a 2x2 table whose display order differs from id order.

    Rows display slot RS2 then RS1 (RS1 -> R1, RS2 -> R2), so R2 shows first.
    Columns display slot CS1 then CS2, but CS1 -> C2 and CS2 -> C1, so C2
    shows first only through the ordering contents indirection.

    Args:
        cells: Cell text keyed by (column id, row id).
        extra_row_contents: Additional row slot -> id mappings (e.g. stale ones).

    Returns:
        Gzipped MergableDataProto bytes.
    """
    b = TableBuilder()
    row_contents = {RS1: R1, RS2: R2, **(extra_row_contents or {})}
    rows = b.ordered_set([RS2, RS1], row_contents)
    columns = b.ordered_set([CS1, CS2], {CS1: C2, CS2: C1})
    return b.build(rows, columns, b.cell_columns(cells))


def test_parse_table_orders_rows_and_columns_through_contents() -> None:
    """Display order follows the ordering array mapped through contents."""
    table = parse_table_data(build_two_by_two(ALL_CELLS))
    assert table is not None
    assert (table.rows, table.columns) == (2, 2)
    grid = [[table.get_cell(r, c) for c in range(2)] for r in range(2)]
    assert grid == [["b2", "a2"], ["b1", "a1"]]


def test_parse_table_missing_cell_is_empty() -> None:
    """A grid position with no cell entry renders as an empty string."""
    cells = {k: v for k, v in ALL_CELLS.items() if k != (C1, R1)}
    table = parse_table_data(build_two_by_two(cells))
    assert table is not None
    assert (table.rows, table.columns) == (2, 2)
    assert table.get_cell(1, 1) == ""
    assert (1, 1) not in table.cells
    assert table.get_cell(0, 0) == "b2"


def test_parse_table_ignores_stale_slot_mapping() -> None:
    """Contents entries whose slot is not in the ordering array are skipped."""
    cells = {**ALL_CELLS, (C1, R_OLD): "gone"}
    table = parse_table_data(build_two_by_two(cells, {RS_OLD: R_OLD}))
    assert table is not None
    assert (table.rows, table.columns) == (2, 2)
    assert "gone" not in table.cells.values()
    assert sorted(table.cells.values()) == ["a1", "a2", "b1", "b2"]


def test_parse_table_without_ictable_returns_none() -> None:
    """Data with no ICTable object is not treated as a table."""
    b = TableBuilder()
    rows = b.ordered_set([RS1], {RS1: R1})
    columns = b.ordered_set([CS1], {CS1: C1})
    data = b.build(rows, columns, b.cell_columns({(C1, R1): "a1"}), table_type=1)
    assert parse_table_data(data) is None


def test_parse_table_data_returns_none_for_invalid() -> None:
    """Invalid (non-gzip) data returns None."""
    assert parse_table_data(b"not gzip data") is None


def test_parse_table_data_returns_none_for_empty() -> None:
    """An empty gzip payload returns None."""
    assert parse_table_data(gzip.compress(b"")) is None


def test_parse_table_data_returns_none_for_garbage_proto() -> None:
    """Gzipped bytes that are not a valid proto return None without raising."""
    assert parse_table_data(gzip.compress(b"\xff\xff\xff\xff")) is None


def test_parse_table_data_with_real_structure() -> None:
    """A real table from a local database copy decodes to a non-empty grid."""
    db_path = Path.home() / ".cache/noted/NoteStore.sqlite"
    if not db_path.exists():
        pytest.skip("Apple Notes database not available")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = conn.execute("""
        SELECT ZMERGEABLEDATA1
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTYPEUTI = 'com.apple.notes.table'
          AND ZMERGEABLEDATA1 IS NOT NULL
        LIMIT 1
    """).fetchone()
    conn.close()

    if not row:
        pytest.skip("No tables found in database")

    result = parse_table_data(row[0])
    assert result is not None
    assert result.rows > 0
    assert result.columns > 0
