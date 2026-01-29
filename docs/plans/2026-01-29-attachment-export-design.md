# Attachment Export Design

**Date:** 2026-01-29
**Status:** Approved

## Overview

Add ability to export note attachments alongside the note file when using the `view` command, with optional 7zip compression.

## CLI Interface

New options for `view` command:

```python
attachments: bool = typer.Option(
    False,
    "--attachments",
    "-a",
    help="Export attachments alongside note file.",
)
zip_archive: bool = typer.Option(
    False,
    "--zip",
    "-z",
    help="Compress output as 7zip archive (requires --attachments).",
)
```

### Behavior

- `--attachments` without `--export`: Export to current directory using sanitized note title as base name
- `--attachments` with `--export ./output`: Use provided path as base
- `--zip` requires `--attachments` (error if used alone)
- `--zip` creates `{base_name}.7z` instead of directory structure

### Examples

```bash
noted view 123 --attachments              # → ./Meeting_Notes.md + ./Meeting_Notes_attachments/
noted view 123 -a -o ./backup             # → ./backup.md + ./backup_attachments/
noted view 123 -a --zip                   # → ./Meeting_Notes.7z
noted view 123 -a -z -o ./archive         # → ./archive.7z
```

## Output Structure

### Directory Export

```
./Meeting_Notes.md
./Meeting_Notes_attachments/
  photo.jpg
  document.pdf
  manifest.json
```

### Archive Export

```
Meeting_Notes.7z contains:
  Meeting_Notes.md
  Meeting_Notes_attachments/
    photo.jpg
    document.pdf
    manifest.json
```

## Database Layer

New function in `db.py`:

```python
def get_attachment_data(
    conn: sqlite3.Connection,
    identifier: str,
) -> tuple[bytes, str, str | None] | None:
    """Fetch binary data for an attachment.

    Args:
        conn: Database connection.
        identifier: The attachment's unique identifier (UUID).

    Returns:
        Tuple of (binary_data, type_uti, title), or None if not found
        or attachment has no binary data.
    """
    query = """
        SELECT ZDATA, ZTYPEUTI, ZTITLE
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZIDENTIFIER = ?
          AND ZDATA IS NOT NULL
    """
```

### UTI to File Extension Mapping

```python
UTI_EXTENSION_MAP: dict[str, str] = {
    "public.jpeg": ".jpg",
    "public.png": ".png",
    "public.heic": ".heic",
    "public.gif": ".gif",
    "public.tiff": ".tiff",
    "com.compuserve.gif": ".gif",
    "com.adobe.pdf": ".pdf",
    "public.pdf": ".pdf",
    "com.apple.drawing": ".png",
    "com.apple.drawing.2": ".png",
}
```

## Attachment Export Module

New module `src/noted/attachments.py`:

```python
@dataclass
class ExportedAttachment:
    """Result of exporting a single attachment."""
    identifier: str
    filename: str           # Final filename used (after deduplication)
    type_uti: str
    exported: bool          # True if binary data was written
    skip_reason: str | None # Why it wasn't exported (e.g., "No binary data")

@dataclass
class AttachmentExportResult:
    """Summary of attachment export operation."""
    exported: list[ExportedAttachment]
    skipped: list[ExportedAttachment]
    manifest_path: Path | None
    attachments_dir: Path | None

def export_attachments(
    conn: sqlite3.Connection,
    attachments: list[Attachment],
    output_dir: Path,
    base_name: str,
) -> AttachmentExportResult:
    """Export all attachments for a note to disk.

    Creates {base_name}_attachments/ directory containing:
    - Binary files for exportable attachments
    - manifest.json listing all attachments

    Handles filename conflicts with UUID suffix.
    """
```

### Manifest Structure

```json
{
  "note_id": 123,
  "note_title": "Meeting Notes",
  "exported_at": "2026-01-29T10:30:00Z",
  "attachments": [
    {
      "identifier": "abc-123-def",
      "filename": "photo.jpg",
      "type": "Image",
      "type_uti": "public.jpeg",
      "exported": true
    },
    {
      "identifier": "xyz-789",
      "filename": null,
      "type": "Table",
      "type_uti": "com.apple.notes.table",
      "exported": false,
      "skip_reason": "Rendered inline in note content"
    }
  ]
}
```

## Archive Creation

```python
def create_archive(
    base_path: Path,
    note_file: Path,
    attachments_dir: Path | None,
) -> Path:
    """Create 7zip archive containing note and attachments.

    Args:
        base_path: Base path for archive (without extension).
        note_file: Path to the exported note file.
        attachments_dir: Path to attachments directory, or None if no attachments.

    Returns:
        Path to created .7z archive.
    """
```

After archiving, temporary files (note file and attachments directory) are cleaned up.

### Dependency

Add to `pyproject.toml`:

```toml
dependencies = [
    "py7zr>=0.20.0",
]
```

## Non-Exportable Attachments

Some attachment types don't have extractable binary data:

- **Tables** - Rendered inline in note content
- **Links** - Just URLs, no file
- **Maps** - Location data, not an image
- **Tags/Mentions** - Text-based

These are:
1. Skipped during export
2. Included in manifest with `exported: false` and `skip_reason`
3. Summarized in console output (e.g., "Skipped 2 non-exportable: 1 Table, 1 Link")

## Filename Conflict Resolution

When multiple attachments have the same filename, append a shortened UUID:

```
image.jpg
image_a7f3b2.jpg
image_c9d4e1.jpg
```

## User Feedback

Example console output:

```
$ noted view 123 --attachments
✓ Exported to ./Meeting_Notes.md
✓ Exported 3 attachments
⚠ Skipped 2 non-exportable: 1 Table, 1 Link

$ noted view 123 -a --zip
✓ Created archive: ./Meeting_Notes.7z
✓ Exported 3 attachments
⚠ Skipped 2 non-exportable: 1 Table, 1 Link
```

## Implementation Plan

1. **db.py** - Add `get_attachment_data()` function
2. **attachments.py** (new) - Export logic, manifest generation, archive creation
3. **cli.py** - Add `--attachments` and `--zip` options, integrate export flow
4. **pyproject.toml** - Add `py7zr` dependency
5. **tests/** - Add tests for new functionality
