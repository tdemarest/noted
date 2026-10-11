"""Table parsing for Apple Notes CRDT tables.

Apple Notes stores a table in ZMERGEABLEDATA1 as a gzipped MergableDataProto.
The table is a CRDT object graph rather than a grid: one flat list of objects
addressed by index, plus shared lists of key names, type names and UUIDs.

```
MergableDataProto > field 2 MergableDataObject > field 3 data
  entries[]  objects, addressed by ObjectID.object_index
  keys[]     identity, crRows, crColumns, cellColumns, UUIDIndex, ...
  types[]    com.apple.notes.ICTable, com.apple.CRDT.NSUUID, ...
  uuids[]    16 raw bytes each

ICTable custom map { crRows, crColumns, cellColumns, crTableColumnDirection }
crRows / crColumns -> OrderedSet
  ordering.array.attachment[i].uuid  display position i (a "slot" id)
  ordering.contents { slot -> id }   maps each slot to the id cells use
cellColumns -> Dictionary { column id -> Dictionary { row id -> cell } }
cell = entry holding a nested Note (note_text + attribute_run)
```

To read cell (r, c): take slot r from the row ordering array, map it through
the ordering contents to a row id, do the same for the column, then look up
cellColumns[column id][row id]. A missing cell is an empty string, and
ordering contents whose slot is not in the ordering array are ignored.

Field numbers follow the public notestore.proto from
https://github.com/threeplanetssoftware/apple_cloud_notes_parser.
"""

import gzip
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

import betterproto2
from loguru import logger

from noted.models import Table
from noted.protobuf import Note

ICTABLE_TYPE = "com.apple.notes.ICTable"


def _repeated(number: int, proto_type: str) -> list[Any]:
    """Declare a repeated betterproto2 field.

    Args:
        number: Protobuf field number.
        proto_type: betterproto2 type name such as "message", "string" or "bytes".

    Returns:
        A dataclass field with an empty list default.
    """
    return betterproto2.field(number, proto_type, repeated=True)


def _message[T: betterproto2.Message](number: int, message_type: type[T]) -> T:
    """Declare a message field that defaults to an empty message instead of None.

    betterproto2 defaults unset message fields to None, while the graph walk
    below relies on unset references reading as empty messages (the behavior
    of the original betterproto library).

    Args:
        number: Protobuf field number.
        message_type: Message class used as the default factory.

    Returns:
        A dataclass field with an empty message default.
    """
    return dataclass_field(
        default_factory=message_type,
        metadata={"betterproto": betterproto2.FieldMetadata(number, betterproto2.TYPE_MESSAGE)},
    )


@dataclass
class ObjectId(betterproto2.Message):
    """Reference to a value: an integer, a string, or an entry index."""

    unsigned_integer_value: int = betterproto2.field(2, betterproto2.TYPE_UINT64)
    string_value: str = betterproto2.field(4, betterproto2.TYPE_STRING)
    object_index: int = betterproto2.field(6, betterproto2.TYPE_INT32)


@dataclass
class MapEntry(betterproto2.Message):
    """One custom map entry: key is an index into the keys list."""

    key: int = betterproto2.field(1, betterproto2.TYPE_INT32)
    value: ObjectId = _message(2, ObjectId)


@dataclass
class CustomMap(betterproto2.Message):
    """Typed key/value object: type is an index into the types list."""

    type: int = betterproto2.field(1, betterproto2.TYPE_INT32)
    map_entry: list[MapEntry] = _repeated(3, "message")


@dataclass
class DictionaryElement(betterproto2.Message):
    """One dictionary element mapping a key object to a value object."""

    key: ObjectId = _message(1, ObjectId)
    value: ObjectId = _message(2, ObjectId)


@dataclass
class Dictionary(betterproto2.Message):
    """CRDT dictionary of object references."""

    element: list[DictionaryElement] = _repeated(1, "message")


@dataclass
class OrderedSetOrderingArrayAttachment(betterproto2.Message):
    """One position in an ordering array, identified by a raw UUID slot."""

    index: int = betterproto2.field(1, betterproto2.TYPE_INT32)
    uuid: bytes = betterproto2.field(2, betterproto2.TYPE_BYTES)


@dataclass
class OrderedSetOrderingArray(betterproto2.Message):
    """Display order of an ordered set as a list of slot UUIDs."""

    attachment: list[OrderedSetOrderingArrayAttachment] = _repeated(2, "message")


@dataclass
class OrderedSetOrdering(betterproto2.Message):
    """Ordering array plus the slot -> id contents mapping."""

    array: OrderedSetOrderingArray = _message(1, OrderedSetOrderingArray)
    contents: Dictionary = _message(2, Dictionary)


@dataclass
class OrderedSet(betterproto2.Message):
    """CRDT ordered set used for table rows and columns."""

    ordering: OrderedSetOrdering = _message(1, OrderedSetOrdering)


@dataclass
class MergeableDataObjectEntry(betterproto2.Message):
    """One object in the flat entry list; only the fields tables use."""

    dictionary: Dictionary | None = betterproto2.field(6, betterproto2.TYPE_MESSAGE, optional=True)
    note: Note | None = betterproto2.field(10, betterproto2.TYPE_MESSAGE, optional=True)
    custom_map: CustomMap | None = betterproto2.field(13, betterproto2.TYPE_MESSAGE, optional=True)
    ordered_set: OrderedSet | None = betterproto2.field(
        16, betterproto2.TYPE_MESSAGE, optional=True
    )


@dataclass
class MergeableDataObjectData(betterproto2.Message):
    """Flat object graph with shared key, type and UUID lists."""

    entries: list[MergeableDataObjectEntry] = _repeated(3, "message")
    keys: list[str] = _repeated(4, "string")
    types: list[str] = _repeated(5, "string")
    uuids: list[bytes] = _repeated(6, "bytes")


@dataclass
class MergableDataObject(betterproto2.Message):
    """Wrapper holding the object graph."""

    version: int = betterproto2.field(2, betterproto2.TYPE_INT32)
    data: MergeableDataObjectData = _message(3, MergeableDataObjectData)


@dataclass
class MergableDataProto(betterproto2.Message):
    """Root message of ZMERGEABLEDATA1 after gunzip."""

    mergable_data_object: MergableDataObject = _message(2, MergableDataObject)


class _Graph:
    """Resolves object references inside one MergeableDataObjectData."""

    def __init__(self, data: MergeableDataObjectData) -> None:
        """Wrap decoded object data.

        Args:
            data: The decoded object graph.
        """
        self.data = data

    def entry(self, ref: ObjectId) -> MergeableDataObjectEntry | None:
        """Return the entry an ObjectId points at, or None if out of range."""
        index = ref.object_index
        if 0 <= index < len(self.data.entries):
            return self.data.entries[index]
        return None

    def fields(self, custom_map: CustomMap) -> dict[str, ObjectId]:
        """Return a custom map's entries keyed by key name."""
        keys = self.data.keys
        return {keys[e.key]: e.value for e in custom_map.map_entry if 0 <= e.key < len(keys)}

    def type_name(self, custom_map: CustomMap) -> str:
        """Return a custom map's type name, or "" if unknown."""
        types = self.data.types
        return types[custom_map.type] if 0 <= custom_map.type < len(types) else ""

    def uuid(self, ref: ObjectId) -> bytes | None:
        """Resolve a reference to a UUID object into its 16 raw bytes."""
        entry = self.entry(ref)
        if entry is None or entry.custom_map is None:
            return None
        index_ref = self.fields(entry.custom_map).get("UUIDIndex")
        if index_ref is None:
            return None
        n = index_ref.unsigned_integer_value
        return self.data.uuids[n] if n < len(self.data.uuids) else None

    def dictionary(self, ref: ObjectId) -> Dictionary | None:
        """Resolve a reference to a dictionary entry."""
        entry = self.entry(ref)
        return entry.dictionary if entry is not None else None

    def find_table(self) -> CustomMap | None:
        """Return the ICTable custom map, or None if the graph has none."""
        for entry in self.data.entries:
            cm = entry.custom_map
            if cm is not None and self.type_name(cm) == ICTABLE_TYPE:
                return cm
        return None

    def ordered_ids(self, ref: ObjectId | None) -> list[bytes | None]:
        """Return row or column ids in display order for an OrderedSet.

        Each slot in the ordering array is mapped through the ordering
        contents to the id cells use. Contents entries whose slot is not in
        the array are stale and ignored. A slot with no mapping yields None.

        Args:
            ref: Reference to the OrderedSet entry (crRows or crColumns).

        Returns:
            One id (or None) per display position.
        """
        entry = self.entry(ref) if ref is not None else None
        if entry is None or entry.ordered_set is None:
            return []
        ordering = entry.ordered_set.ordering
        slot_to_id: dict[bytes, bytes] = {}
        for element in ordering.contents.element:
            slot = self.uuid(element.key)
            target = self.uuid(element.value)
            if slot is not None and target is not None:
                slot_to_id[slot] = target
        return [slot_to_id.get(a.uuid) for a in ordering.array.attachment]

    def cell_columns(self, ref: ObjectId | None) -> dict[bytes, dict[bytes, str]]:
        """Return cell text as {column id: {row id: text}}.

        Args:
            ref: Reference to the cellColumns dictionary.

        Returns:
            Nested mapping of column id to row id to cell text.
        """
        outer = self.dictionary(ref) if ref is not None else None
        if outer is None:
            return {}
        columns: dict[bytes, dict[bytes, str]] = {}
        for col_element in outer.element:
            col_id = self.uuid(col_element.key)
            inner = self.dictionary(col_element.value)
            if col_id is None or inner is None:
                continue
            column = columns.setdefault(col_id, {})
            for row_element in inner.element:
                row_id = self.uuid(row_element.key)
                cell = self.entry(row_element.value)
                if row_id is not None and cell is not None and cell.note is not None:
                    column[row_id] = cell.note.note_text
        return columns


def _decode_table(raw: bytes) -> Table | None:
    """Decode a decompressed MergableDataProto into a Table.

    Args:
        raw: Gunzipped ZMERGEABLEDATA1 bytes.

    Returns:
        The table grid, or None if the data has no ICTable object.
    """
    proto = MergableDataProto().parse(raw)
    graph = _Graph(proto.mergable_data_object.data)
    table = graph.find_table()
    if table is None:
        logger.debug("No ICTable object in table data")
        return None

    fields = graph.fields(table)
    row_ids = graph.ordered_ids(fields.get("crRows"))
    col_ids = graph.ordered_ids(fields.get("crColumns"))
    columns = graph.cell_columns(fields.get("cellColumns"))

    cells: dict[tuple[int, int], str] = {}
    for c, col_id in enumerate(col_ids):
        column = columns.get(col_id, {}) if col_id is not None else {}
        for r, row_id in enumerate(row_ids):
            text = column.get(row_id) if row_id is not None else None
            if text:
                cells[(r, c)] = text
    return Table(rows=len(row_ids), columns=len(col_ids), cells=cells)


def parse_table_data(data: bytes, summary: str = "") -> Table | None:
    """Parse gzipped CRDT table protobuf from ZMERGEABLEDATA1.

    Args:
        data: Gzipped protobuf bytes from the database.
        summary: Unused; kept for backward compatibility with callers.

    Returns:
        Table in display order, or None if the data cannot be decoded.
    """
    del summary  # The CRDT ordering is authoritative; ZSUMMARY is not needed.
    try:
        raw = gzip.decompress(data)
    except (OSError, EOFError) as e:
        logger.debug(f"Failed to decompress table data: {e}")
        return None
    if not raw:
        return None
    try:
        return _decode_table(raw)
    except Exception as e:  # Malformed protobuf: treat as undecodable.
        logger.debug(f"Failed to decode table structure: {e}")
        return None
