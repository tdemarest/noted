# Apple Notes Attachment Structure

This document describes how Apple Notes stores attachments and how to extract them. This information was reverse-engineered through analysis of the NoteStore.sqlite database and file system.

## Overview

Apple Notes stores attachments as **files on disk**, not in the SQLite database. The database contains metadata and references that point to the actual files.

Key characteristics:
- Attachments are embedded in notes with a specific UTI type (e.g., `public.jpeg`, `com.adobe.pdf`)
- Binary data is stored on the file system, not in the database
- The database tracks attachment metadata via foreign key relationships
- Multiple database records work together: attachment record → media record → file on disk

## Database Schema

### ZICCLOUDSYNCINGOBJECT Table

This table contains both notes and attachments. Attachment records are identified by having:
- `ZTYPEUTI` set to a file type (e.g., `public.jpeg`, `public.png`, `com.adobe.pdf`)
- `ZNOTE` pointing to the parent note's `Z_PK`

Key columns for attachments:

| Column | Type | Purpose |
|--------|------|---------|
| `Z_PK` | INTEGER | Primary key |
| `ZIDENTIFIER` | TEXT | UUID uniquely identifying the attachment |
| `ZTYPEUTI` | TEXT | Uniform Type Identifier (e.g., `public.jpeg`) |
| `ZTITLE` | TEXT | Display name/title of attachment |
| `ZNOTE` | INTEGER | Foreign key to parent note's `Z_PK` |
| `ZMEDIA` | INTEGER | Foreign key to media record's `Z_PK` |

### Attachment → Media Relationship

Each attachment record points to a **media record** via `ZMEDIA`. The media record contains:

| Column | Type | Purpose |
|--------|------|---------|
| `Z_PK` | INTEGER | Primary key (referenced by attachment's `ZMEDIA`) |
| `ZIDENTIFIER` | TEXT | UUID used in file system path |
| `ZFILENAME` | TEXT | Actual filename on disk |
| `ZFILESIZE` | INTEGER | File size in bytes (often NULL—calculate from disk instead) |

### Attachment Size Notes

**Important findings about `ZFILESIZE`:**

1. **`ZFILESIZE` is often unpopulated.** Despite the column existing in the database schema, it is frequently NULL even for attachments with physical files on disk. Testing shows 0 out of 3480 media records had `ZFILESIZE` populated.

2. **Calculate sizes from disk instead.** To get accurate file sizes, stat the actual files on disk rather than relying on the database:
   ```python
   file_path = find_media_file(media_id, filename)
   if file_path:
       size = file_path.stat().st_size
   ```

3. **Inline attachments have no file size.** Non-exportable types like tables (`com.apple.notes.table`), links (`public.url`), and text attachments have `ZMEDIA = NULL`. These are rendered inline and don't occupy separate file storage.

4. **A note with "8 attachments, 0 bytes" means all are inline types.** Tables, links, hashtags, and mentions have no physical files on disk.

## File System Structure

Attachments are stored in the Apple Notes container at:

```
~/Library/Group Containers/group.com.apple.notes/
```

### Directory Layout

```
group.com.apple.notes/
├── NoteStore.sqlite          # Main database
├── NoteStore.sqlite-shm
├── NoteStore.sqlite-wal
├── Accounts/
│   └── <ACCOUNT_UUID>/       # e.g., A1B2C3D4-E5F6-7890-ABCD-EF1234567890
│       ├── Media/
│       │   └── <MEDIA_IDENTIFIER>/   # From media record's ZIDENTIFIER
│       │       └── 1_<SUBFOLDER_UUID>/
│       │           └── <FILENAME>    # From media record's ZFILENAME
│       ├── Previews/         # Preview images
│       ├── Thumbnails/       # Thumbnail images
│       ├── FallbackPDFs/     # PDF fallbacks
│       └── Paper/            # Handwriting/drawing data
└── Thumbnails/               # Additional thumbnails
```

### Example Path

For an attachment with:
- Media record `ZIDENTIFIER`: `CCCCCCCC-DDDD-EEEE-FFFF-111111111111`
- Media record `ZFILENAME`: `vacation_photo.jpg`
- Account UUID: `A1B2C3D4-E5F6-7890-ABCD-EF1234567890`

The file is located at:
```
~/Library/Group Containers/group.com.apple.notes/Accounts/A1B2C3D4-E5F6-7890-ABCD-EF1234567890/Media/CCCCCCCC-DDDD-EEEE-FFFF-111111111111/1_FFFFFFFF-1111-2222-3333-444444444444/vacation_photo.jpg
```

### Subfolder Naming

The subfolder within each media directory follows the pattern `1_<UUID>`. The UUID appears to be generated when the attachment is created. There is typically only one subfolder per media directory.

## UTI Types

### Exportable Types (Have Binary Data)

| UTI | Human Name | File Extension |
|-----|------------|----------------|
| `public.jpeg` | Image | `.jpg` |
| `public.png` | Image | `.png` |
| `public.heic` | Image | `.heic` |
| `public.gif` | Image | `.gif` |
| `public.tiff` | Image | `.tiff` |
| `com.compuserve.gif` | Image | `.gif` |
| `com.adobe.pdf` | PDF | `.pdf` |
| `public.pdf` | PDF | `.pdf` |
| `com.apple.drawing` | Drawing | `.png` |
| `com.apple.drawing.2` | Drawing | `.png` |

### Non-Exportable Types (No Binary File)

| UTI | Human Name | Reason |
|-----|------------|--------|
| `com.apple.notes.table` | Table | Rendered inline (stored as CRDT in `ZMERGEABLEDATA1`) |
| `com.apple.notes.gallery` | Gallery | Container, no single file |
| `com.apple.notes.inlinetextattachment` | Text | Inline text, no file |
| `com.apple.notes.inlinetextattachment.hashtag` | Tag | Hashtag, no file |
| `com.apple.notes.inlinetextattachment.mention` | Mention | Mention, no file |
| `public.url` | Link | URL reference, no file |
| `com.apple.mapkit.map-item` | Map | Location data, no file |
| `public.vcard` | Contact | Contact data, no file |

## Querying Attachments

### Get Attachment Metadata for a Note

```sql
SELECT
    att.ZIDENTIFIER as attachment_id,
    att.ZTYPEUTI as type,
    att.ZTITLE as title,
    att.ZMEDIA,
    media.ZIDENTIFIER as media_id,
    media.ZFILENAME as filename
FROM ZICCLOUDSYNCINGOBJECT att
LEFT JOIN ZICCLOUDSYNCINGOBJECT media ON att.ZMEDIA = media.Z_PK
WHERE att.ZNOTE = ?
  AND att.ZTYPEUTI IS NOT NULL
```

Note: `media.ZFILESIZE` exists but is often NULL. Get file sizes from disk instead.

### Get Attachment Statistics for a Note

Since `ZFILESIZE` is often unpopulated, calculate sizes from disk:

```python
def get_attachment_stats(conn, note_id):
    """Get attachment count and total size from disk."""
    query = """
        SELECT
            media.ZIDENTIFIER as media_id,
            media.ZFILENAME as filename
        FROM ZICCLOUDSYNCINGOBJECT att
        LEFT JOIN ZICCLOUDSYNCINGOBJECT media ON att.ZMEDIA = media.Z_PK
        WHERE att.ZNOTE = ?
          AND att.ZIDENTIFIER IS NOT NULL
          AND att.ZTYPEUTI IS NOT NULL
    """
    rows = conn.execute(query, (note_id,)).fetchall()

    total_size = 0
    for row in rows:
        if row["media_id"] and row["filename"]:
            file_path = find_media_file(row["media_id"], row["filename"])
            if file_path:
                total_size += file_path.stat().st_size

    return {"count": len(rows), "total_size": total_size}
```

Note: `total_size` will be 0 if all attachments are inline types (tables, links, etc.).

### Get Attachment Names (for Display)

```sql
SELECT ZIDENTIFIER, ZTITLE
FROM ZICCLOUDSYNCINGOBJECT
WHERE ZNOTE = ?
  AND ZIDENTIFIER IS NOT NULL
  AND ZTITLE IS NOT NULL
```

## Attachment Extraction Algorithm

```python
def get_attachment_data(conn, attachment_identifier):
    """Fetch binary data for an attachment."""

    # 1. Query attachment and linked media record
    query = """
        SELECT
            att.ZTYPEUTI,
            att.ZTITLE as att_title,
            media.ZIDENTIFIER as media_id,
            media.ZFILENAME
        FROM ZICCLOUDSYNCINGOBJECT att
        LEFT JOIN ZICCLOUDSYNCINGOBJECT media ON att.ZMEDIA = media.Z_PK
        WHERE att.ZIDENTIFIER = ?
    """
    row = conn.execute(query, (attachment_identifier,)).fetchone()

    if not row or not row["media_id"] or not row["ZFILENAME"]:
        return None

    # 2. Build file path
    # Search through Accounts/*/Media/<media_id>/*/<filename>
    file_path = find_media_file(row["media_id"], row["ZFILENAME"])

    if not file_path:
        return None

    # 3. Read and return file contents
    return (file_path.read_bytes(), row["ZTYPEUTI"], row["att_title"])


def find_media_file(media_identifier, filename):
    """Find media file on disk."""
    notes_dir = Path.home() / "Library/Group Containers/group.com.apple.notes"
    accounts_dir = notes_dir / "Accounts"

    for account_dir in accounts_dir.iterdir():
        if not account_dir.is_dir():
            continue
        media_dir = account_dir / "Media" / media_identifier
        if not media_dir.exists():
            continue

        # File is in a subfolder (1_<UUID>)
        for subfolder in media_dir.iterdir():
            if subfolder.is_dir():
                file_path = subfolder / filename
                if file_path.exists():
                    return file_path

    return None
```

## Note Content and Attachments

### Attachment Placeholders

In the note's protobuf content (`ZICNOTEDATA.ZDATA`), attachments are represented by the **Object Replacement Character** (U+FFFC, `\ufffc`).

Each placeholder corresponds to an `AttributeRun` in the protobuf with:
- Field 12: `attachment_info` containing:
  - Field 1: `attachment_identifier` (UUID string)
  - Field 2: `type_uti` (UTI string)

### Parsing Flow

```
Note Content (gzip protobuf)
    │
    ├── Text with U+FFFC placeholders
    │
    └── AttributeRuns with attachment_info
            │
            ├── attachment_identifier → ZICCLOUDSYNCINGOBJECT.ZIDENTIFIER
            │                                   │
            │                                   └── ZMEDIA → media record
            │                                               │
            │                                               └── File on disk
            │
            └── type_uti → Determines if exportable
```

## Export Manifest

When exporting attachments, a `manifest.json` is created:

```json
{
  "note_id": 10971,
  "note_title": "Vehicle Service Record",
  "exported_at": "2026-01-29T08:56:17.839Z",
  "attachments": [
    {
      "identifier": "11111111-2222-3333-4444-555555555555",
      "filename": "receipt_photo.jpg",
      "type_uti": "public.jpeg",
      "exported": true
    },
    {
      "identifier": "66666666-7777-8888-9999-AAAAAAAAAAAA",
      "filename": null,
      "type_uti": "com.apple.notes.table",
      "exported": false,
      "skip_reason": "Rendered inline in note content"
    }
  ]
}
```

## Filename Handling

### Sanitization

Filenames from the database may contain invalid characters. Sanitize by:
1. Replace spaces with underscores
2. Remove characters invalid on Windows/macOS/Linux: `/ \ : * ? " < > |`
3. Remove control characters
4. Default to "attachment" if nothing remains

### Duplicate Resolution

When multiple attachments have the same filename, append a UUID suffix:
```
photo.jpg
photo_abc123.jpg
photo_def456.jpg
```

## References

- Apple Notes database: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- Attachment records: `ZICCLOUDSYNCINGOBJECT` where `ZTYPEUTI IS NOT NULL`
- Media files: `~/Library/Group Containers/group.com.apple.notes/Accounts/*/Media/`
- Related: [Apple Notes CRDT Table Structure](./apple-notes-crdt-table-structure.md)
