# Full Export Design

**Date:** 2026-01-29
**Status:** Implemented

## Overview

Add ability to export all Apple Notes to a structured folder hierarchy with a master index, optionally compressed as a single 7zip archive.

### Use Case Priority

1. **Backup** - Disaster recovery, archive for safekeeping
2. **Sharing** - Giving notes to someone else
3. **Migration** - Moving to another note system

## CLI Interface

New `export` command with flags:

```python
@app.command()
def export(
    note_id: str | None = typer.Argument(
        None,
        help="Note ID or UUID to export. Omit for --all.",
    ),
    all_notes: bool = typer.Option(
        False,
        "--all",
        "-A",
        help="Export all notes.",
    ),
    output: Path = typer.Option(
        Path("./notes_export"),
        "--output",
        "-o",
        help="Output directory (or file for single note).",
    ),
    zip_archive: bool = typer.Option(
        False,
        "--zip",
        "-z",
        help="Also create 7zip archive.",
    ),
    folder_filter: str | None = typer.Option(
        None,
        "--folder",
        "-f",
        help="Export only notes from this folder.",
    ),
    exclude_deleted: bool = typer.Option(
        False,
        "--exclude-deleted",
        help="Exclude notes in Recently Deleted.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed output for each note.",
    ),
) -> None:
    """Export notes to markdown with attachments."""
```

### Usage Examples

```bash
# Export all notes
noted export --all

# Export all notes with archive
noted export --all --zip

# Export to custom location
noted export --all -o ~/Backups/notes_2026-01-29

# Export single note (replaces current view --attachments behavior)
noted export 42
noted export "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"

# Export only Work folder
noted export --all --folder "Work"

# Export excluding deleted notes
noted export --all --exclude-deleted

# Verbose output showing each note
noted export --all --verbose
```

## Output Structure

### Full Export Structure

```
notes_export/
  index.json                              # Master manifest
  Work/
    Meeting_Notes/
      Meeting_Notes.md
      attachments/
        photo.jpg
        document.pdf
        manifest.json
    Project_Plan/
      Project_Plan.md
      attachments/
        diagram.png
        manifest.json
  Personal/
    Journal_2026-01-15/
      Journal_2026-01-15.md
      attachments/
        ...
  Recently Deleted/
    Old_Note/
      Old_Note.md
  notes_export.7z                         # Created if --zip flag used
```

### Folder Naming

- Folder names mirror Apple Notes folder names
- Note folder names are sanitized note titles
- UUID suffix added **only on conflict** (e.g., `Meeting_Notes_a7f3b2/` when duplicate titles exist in same folder)

### Single Note Export Structure

When exporting a single note with `noted export 42`, uses the same flat structure as current `view --attachments`:

```
./Note_Title.md
./Note_Title_attachments/
    photo.jpg
    manifest.json
```

This differs from full export (which uses nested folders) to maintain backwards compatibility and simpler single-note workflows.

## Master Index Format

`index.json` at the root of the export:

```json
{
  "export_version": "1.0",
  "exported_at": "2026-01-29T10:30:00Z",
  "source": "Apple Notes",
  "statistics": {
    "total_notes": 150,
    "total_folders": 12,
    "total_attachments": 89,
    "locked_notes": 3,
    "failed_exports": 1
  },
  "folders": [
    {
      "name": "Work",
      "path": "Work/",
      "note_count": 25
    },
    {
      "name": "Personal",
      "path": "Personal/",
      "note_count": 45
    },
    {
      "name": "Recently Deleted",
      "path": "Recently Deleted/",
      "note_count": 5
    }
  ],
  "notes": [
    {
      "id": 42,
      "identifier": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
      "title": "Meeting Notes",
      "folder": "Work",
      "path": "Work/Meeting_Notes/Meeting_Notes.md",
      "created": "2026-01-15T09:00:00Z",
      "modified": "2026-01-20T14:30:00Z",
      "attachment_count": 3,
      "locked": false,
      "export_status": "success"
    },
    {
      "id": 55,
      "identifier": "LOCKED-NOTE-UUID",
      "title": "Secret Note",
      "folder": "Personal",
      "path": "Personal/Secret_Note/Secret_Note.md",
      "created": "2026-01-10T08:00:00Z",
      "modified": "2026-01-10T08:00:00Z",
      "attachment_count": 0,
      "locked": true,
      "export_status": "locked"
    }
  ],
  "errors": [
    {
      "note_id": 99,
      "identifier": "CORRUPT-NOTE-UUID",
      "title": "Corrupt Note",
      "folder": "Work",
      "error": "Failed to decompress note content"
    }
  ]
}
```

## Per-Note Structure

Each note gets its own folder:

```
Note_Title/
  Note_Title.md                    # The note content as markdown
  attachments/                     # Only if note has attachments
    photo.jpg
    document.pdf
    manifest.json                  # Per-note attachment manifest
```

### Per-Note Attachment Manifest

Same structure as current single-note export:

```json
{
  "note_id": 42,
  "note_identifier": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
  "note_title": "Meeting Notes",
  "exported_at": "2026-01-29T10:30:00Z",
  "attachments": [
    {
      "identifier": "att-uuid-1",
      "filename": "photo.jpg",
      "type_uti": "public.jpeg",
      "exported": true
    },
    {
      "identifier": "att-uuid-2",
      "filename": null,
      "type_uti": "com.apple.notes.table",
      "exported": false,
      "skip_reason": "Rendered inline in note content"
    }
  ]
}
```

## Locked Notes Handling

When a locked note is encountered:

1. **Console warning**: `Warning: Note "Secret Note" is locked, creating placeholder`
2. **Placeholder file**: Create markdown file with locked message
3. **Manifest entry**: `export_status: "locked"`

### Locked Note Placeholder Content

```markdown
# Secret Note

> **This note is locked and cannot be exported.**
>
> To export this note, unlock it in Apple Notes and run the export again.

---
*Note ID: 55*
*Identifier: LOCKED-NOTE-UUID*
*Folder: Personal*
```

## Error Handling

### Export Errors

When a note fails to export (corrupt data, missing content, etc.):

1. **Skip and continue** - Don't abort the entire export
2. **Console warning**: `Error: Failed to export "Corrupt Note": <error message>`
3. **Log in errors array**: Include in `index.json` errors section
4. **Summary at end**: `Exported 149 notes. 1 failed (see index.json for details).`

### Validation Errors

- `--zip` without `--all` or note_id: Error
- Invalid `--folder` name: Warning, export nothing from that filter
- Output directory not writable: Error before starting

## Archive Behavior

When `--zip` flag is used:

1. Create the full folder structure
2. Create `{output_name}.7z` archive containing everything
3. **Keep both** - User gets folder structure AND archive

Archive location: Same parent directory as export folder
- Export to `./notes_export/` → Archive at `./notes_export.7z`
- Export to `~/Backups/my_notes/` → Archive at `~/Backups/my_notes.7z`

## Progress Feedback

### Default (Progress Bar)

```
Exporting notes...
[████████████████████░░░░░░░░░░░░░░░░░░░░] 52/150 notes
```

### Verbose Mode (`--verbose`)

```
Exporting notes...
  ✓ Work/Meeting_Notes
  ✓ Work/Project_Plan (3 attachments)
  ⚠ Personal/Secret_Note (locked)
  ✗ Work/Corrupt_Note (failed: decompression error)
  ✓ Personal/Journal_2026-01-15
  ...

Exported 148 notes to ./notes_export/
  - 3 locked (placeholders created)
  - 1 failed (see index.json)
  - 89 attachments exported
Created archive: ./notes_export.7z
```

## Implementation Plan

### Phase 1: Core Export Infrastructure

1. **Create `src/noted/export.py` module**
   - `ExportResult` dataclass for tracking outcomes
   - `ExportOptions` dataclass for configuration
   - `generate_master_index()` function

2. **Add database functions to `db.py`**
   - `get_all_notes()` - Fetch all notes with folder info
   - `get_folders()` - Get list of all folders

3. **Extend `attachments.py`**
   - Update `export_attachments()` to work with new structure
   - Add `export_note_folder()` function

### Phase 2: CLI Integration

4. **Add `export` command to `cli.py`**
   - Argument parsing and validation
   - Progress bar with Rich
   - Error handling and summary

5. **Remove `--attachments` and `--zip` from `view` command**
   - Clean removal of flags
   - Update `view` command tests
   - Update CLAUDE.md quick start examples

### Phase 3: Archive and Polish

6. **Archive creation**
   - Extend `create_archive()` for full export
   - Handle large archives efficiently

7. **Testing**
   - Unit tests for new functions
   - Integration tests for full export flow

## Migration from `view --attachments`

The `--attachments` and `--zip` flags will be **removed from the `view` command** when `export` is added. The `view` command returns to its original purpose: displaying note content in the terminal or exporting to a single file.

- `noted view 42` - Display in terminal (unchanged)
- `noted view 42 --markdown` - Output as markdown (unchanged)
- `noted view 42 -o file.md` - Export to file (unchanged)
- `noted view 42 --attachments` - **Removed**, use `noted export 42` instead

## Future Considerations

- **Incremental export**: Only export notes modified since last export
- **HTML output**: Option to export as HTML instead of/in addition to markdown
- **PDF export**: Generate PDFs from notes
- **Import**: Reverse operation to import exported notes back

## References

- [Attachment Export Design](./2026-01-29-attachment-export-design.md) - Single note export design
- [Attachment Export Implementation](./2026-01-29-attachment-export-implementation.md) - Implementation details
