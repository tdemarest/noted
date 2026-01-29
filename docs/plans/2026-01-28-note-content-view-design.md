# Design: Note Content View Command

## Overview

Add a `noted view <id>` command to display the full content of a single note. This establishes the protobuf parsing foundation for future features (search, export).

## Architecture

### Data Flow

```
CLI (view command)
  → db.get_note_content(id)        → raw gzip bytes
  → protobuf.parse_note_data(bytes) → NoteContent dataclass
  → display.display_note_view()     → terminal output
```

### New Module: `src/noted/protobuf.py`

Handles all protobuf parsing:
- Defines betterproto dataclasses matching Apple's schema
- Decompresses gzip data from ZDATA
- Parses protobuf into Python objects
- Extracts plain text from parsed structure

### Protobuf Schema

Minimal schema for plain text extraction:

```
NoteStoreProto (root)
  └── Document (field 2)
        └── Note (field 3)
              ├── note_text: string (field 2)
              └── attribute_run: repeated AttributeRun (field 5, ignored for now)
```

betterproto dataclasses:

```python
@dataclass
class Note(betterproto.Message):
    note_text: str = betterproto.string_field(2)

@dataclass
class Document(betterproto.Message):
    note: Note = betterproto.message_field(3)

@dataclass
class NoteStoreProto(betterproto.Message):
    document: Document = betterproto.message_field(2)
```

### Database Query

New function in `db.py`:

```python
def get_note_content(conn: sqlite3.Connection, note_id: int) -> bytes | None:
    """Fetch raw ZDATA bytes for a note by ID."""
```

SQL:
```sql
SELECT nd.ZDATA
FROM ZICCLOUDSYNCINGOBJECT n
JOIN ZICNOTEDATA nd ON nd.ZNOTE = n.Z_PK
WHERE n.Z_PK = ?
```

### CLI Command

```bash
uv run noted view 42
```

Takes note ID from `list` output, displays title + body text.

### Display Format

```
┌─────────────────────────────────────────┐
│ Meeting Notes                           │
│ Folder: Work  │  Modified: 2026-01-28   │
└─────────────────────────────────────────┘

Discussed Q1 roadmap with the team...
```

Rich panel for header, plain text body. No truncation.

### New Model

```python
@dataclass
class NoteContent:
    text: str  # Plain text extracted from protobuf
```

### Error Handling

- Note ID doesn't exist → "Note not found"
- Note is locked (encrypted) → "Note is locked and cannot be read"
- No content data → "Note has no content"

Locked notes detected by checking gzip magic bytes (0x1F 0x8B).

## File Changes

| File | Change |
|------|--------|
| `src/noted/protobuf.py` | NEW: betterproto schema + `parse_note_data()` |
| `src/noted/db.py` | Add `get_note_content()` |
| `src/noted/models.py` | Add `NoteContent` dataclass |
| `src/noted/display.py` | Add `display_note_view()` |
| `src/noted/cli.py` | Add `view` command |
| `pyproject.toml` | Add betterproto dependency |

## Dependencies

```toml
"betterproto>=2.0.0b6"
```

## References

- [apple_cloud_notes_parser](https://github.com/threeplanetssoftware/apple_cloud_notes_parser) - Reverse-engineered protobuf schema
- [Ciofeca Forensics - The Protobuf](https://ciofecaforensics.com/2020/09/18/apple-notes-revisited-protobuf/) - Schema documentation
- [notesutils](https://github.com/dunhamsteve/notesutils/blob/master/notes.md) - Additional schema notes
