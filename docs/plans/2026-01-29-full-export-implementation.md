# Full Export Implementation Plan

> **Status:** ✅ COMPLETED (2026-01-29)

**Goal:** Add `noted export` command supporting both single-note and full export with attachments.

**Architecture:** New `export.py` module handles export orchestration. Database layer gets functions for fetching all notes and folders. CLI gets new `export` command; `view` command loses `--attachments` and `--zip` flags.

**Tech Stack:** Python 3.14+, py7zr, Rich progress bars, existing sqlite3/typer stack.

---

## Task 1: Add Database Functions for Full Export

**Files:**
- Modify: `src/noted/db.py`
- Test: `tests/test_db.py`

### Step 1: Write failing tests

Add to `tests/test_db.py`:

```python
def test_get_all_notes_includes_deleted(tmp_path: Path) -> None:
    """Test get_all_notes includes notes marked for deletion when requested."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTITLE1 TEXT,
            ZTITLE2 TEXT,
            ZFOLDER INTEGER,
            ZCREATIONDATE REAL,
            ZMODIFICATIONDATE REAL,
            ZMARKEDFORDELETION INTEGER DEFAULT 0
        )
    """)
    # Regular note
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "uuid-1", "Active Note", None, None, 0, 0, 0),
    )
    # Deleted note
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (2, "uuid-2", "Deleted Note", None, None, 0, 0, 1),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    from noted.db import get_all_notes

    # Without deleted
    notes = get_all_notes(conn, include_deleted=False)
    assert len(notes) == 1
    assert notes[0].title == "Active Note"

    # With deleted
    notes = get_all_notes(conn, include_deleted=True)
    assert len(notes) == 2

    conn.close()


def test_get_folders(tmp_path: Path) -> None:
    """Test get_folders returns folder names and note counts."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTITLE1 TEXT,
            ZTITLE2 TEXT,
            ZFOLDER INTEGER,
            ZMARKEDFORDELETION INTEGER DEFAULT 0
        )
    """)
    # Folder
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?)",
        (1, "folder-1", None, "Work", None, 0),
    )
    # Notes in folder
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?)",
        (2, "uuid-1", "Note 1", None, 1, 0),
    )
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?)",
        (3, "uuid-2", "Note 2", None, 1, 0),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    from noted.db import get_folders

    folders = get_folders(conn)
    assert len(folders) == 1
    assert folders[0]["name"] == "Work"
    assert folders[0]["note_count"] == 2

    conn.close()
```

### Step 2: Run tests to verify they fail

```bash
uv run pytest tests/test_db.py::test_get_all_notes_includes_deleted -v
uv run pytest tests/test_db.py::test_get_folders -v
```

Expected: FAIL with "cannot import name"

### Step 3: Implement functions

Add to `src/noted/db.py` after `get_note()`:

```python
@dataclass
class FolderInfo:
    """Information about a notes folder.

    Attributes:
        name: Folder name.
        identifier: Folder UUID.
        note_count: Number of notes in folder.
    """

    name: str
    identifier: str
    note_count: int


def get_all_notes(
    conn: sqlite3.Connection,
    folder: str | None = None,
    include_deleted: bool = True,
) -> list[Note]:
    """Fetch all notes from the database.

    Unlike list_notes(), this function can include deleted notes
    and is intended for full export operations.

    Args:
        conn: Database connection.
        folder: Filter by folder name, or None for all folders.
        include_deleted: If True, include notes in Recently Deleted.

    Returns:
        List of Note objects sorted by folder then modification date.
    """
    query = """
        SELECT
            n.Z_PK as id,
            n.ZIDENTIFIER as identifier,
            n.ZTITLE1 as title,
            f.ZTITLE2 as folder,
            n.ZCREATIONDATE as created,
            n.ZMODIFICATIONDATE as modified,
            n.ZMARKEDFORDELETION as deleted
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
        WHERE n.ZTITLE1 IS NOT NULL
    """
    params: list[str | int] = []

    if not include_deleted:
        query += " AND (n.ZMARKEDFORDELETION IS NULL OR n.ZMARKEDFORDELETION != 1)"

    if folder is not None:
        query += " AND f.ZTITLE2 = ?"
        params.append(folder)

    query += " ORDER BY f.ZTITLE2, n.ZMODIFICATIONDATE DESC"

    cursor = conn.execute(query, params)
    notes = []
    for row in cursor:
        notes.append(
            Note(
                id=row["id"],
                identifier=row["identifier"] or "",
                title=row["title"] or "(Untitled)",
                folder=row["folder"] if not row["deleted"] else "Recently Deleted",
                created=apple_timestamp_to_datetime(row["created"]),
                modified=apple_timestamp_to_datetime(row["modified"]),
            )
        )
    return notes


def get_folders(conn: sqlite3.Connection) -> list[FolderInfo]:
    """Get all folders with their note counts.

    Args:
        conn: Database connection.

    Returns:
        List of FolderInfo objects sorted by name.
    """
    query = """
        SELECT
            f.ZTITLE2 as name,
            f.ZIDENTIFIER as identifier,
            COUNT(n.Z_PK) as note_count
        FROM ZICCLOUDSYNCINGOBJECT f
        LEFT JOIN ZICCLOUDSYNCINGOBJECT n ON n.ZFOLDER = f.Z_PK
            AND n.ZTITLE1 IS NOT NULL
        WHERE f.ZTITLE2 IS NOT NULL
        GROUP BY f.Z_PK, f.ZTITLE2, f.ZIDENTIFIER
        ORDER BY f.ZTITLE2
    """
    cursor = conn.execute(query)
    return [
        FolderInfo(
            name=row["name"],
            identifier=row["identifier"] or "",
            note_count=row["note_count"],
        )
        for row in cursor
    ]
```

Also add import and export for `FolderInfo` dataclass at top of file.

### Step 4: Run tests to verify they pass

```bash
uv run pytest tests/test_db.py -k "get_all_notes or get_folders" -v
```

### Step 5: Commit

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): add get_all_notes and get_folders functions

get_all_notes fetches all notes with optional deleted/folder filters.
get_folders returns folder names with note counts for export.
EOF
)"
```

---

## Task 2: Create Export Module with Data Models

**Files:**
- Create: `src/noted/export.py`
- Test: `tests/test_export.py`

### Step 1: Write failing tests

Create `tests/test_export.py`:

```python
"""Tests for noted.export module."""

from pathlib import Path

from noted.export import ExportOptions, NoteExportResult, FullExportResult


def test_export_options_defaults() -> None:
    """Test ExportOptions has sensible defaults."""
    opts = ExportOptions(output_dir=Path("./export"))
    assert opts.output_dir == Path("./export")
    assert opts.include_deleted is True
    assert opts.create_archive is False
    assert opts.folder_filter is None
    assert opts.verbose is False


def test_note_export_result_success() -> None:
    """Test NoteExportResult for successful export."""
    result = NoteExportResult(
        note_id=42,
        identifier="uuid-123",
        title="Test Note",
        folder="Work",
        status="success",
        path=Path("Work/Test_Note/Test_Note.md"),
        attachment_count=3,
        error=None,
    )
    assert result.status == "success"
    assert result.error is None


def test_note_export_result_locked() -> None:
    """Test NoteExportResult for locked note."""
    result = NoteExportResult(
        note_id=55,
        identifier="uuid-456",
        title="Secret",
        folder="Personal",
        status="locked",
        path=Path("Personal/Secret/Secret.md"),
        attachment_count=0,
        error=None,
    )
    assert result.status == "locked"


def test_full_export_result() -> None:
    """Test FullExportResult aggregates statistics."""
    result = FullExportResult(
        output_dir=Path("./notes_export"),
        archive_path=None,
        total_notes=100,
        exported_count=97,
        locked_count=2,
        failed_count=1,
        total_attachments=50,
        folders=["Work", "Personal"],
        notes=[],
        errors=[],
    )
    assert result.total_notes == 100
    assert result.exported_count == 97
```

### Step 2: Run tests to verify they fail

```bash
uv run pytest tests/test_export.py::test_export_options_defaults -v
```

Expected: FAIL with "No module named 'noted.export'"

### Step 3: Implement data models

Create `src/noted/export.py`:

```python
"""Full export functionality for Apple Notes.

Handles exporting all notes to a structured folder hierarchy
with master index and optional 7zip compression.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExportOptions:
    """Configuration options for export operation.

    Attributes:
        output_dir: Directory to export to.
        include_deleted: Include notes in Recently Deleted.
        create_archive: Also create .7z archive.
        folder_filter: Only export notes from this folder.
        verbose: Show detailed progress for each note.
    """

    output_dir: Path
    include_deleted: bool = True
    create_archive: bool = False
    folder_filter: str | None = None
    verbose: bool = False


@dataclass
class NoteExportResult:
    """Result of exporting a single note.

    Attributes:
        note_id: Database row ID.
        identifier: Note UUID.
        title: Note title.
        folder: Folder name.
        status: Export status ('success', 'locked', 'failed').
        path: Relative path to exported note file.
        attachment_count: Number of attachments exported.
        error: Error message if status is 'failed'.
    """

    note_id: int
    identifier: str
    title: str
    folder: str | None
    status: str  # 'success', 'locked', 'failed'
    path: Path | None
    attachment_count: int
    error: str | None


@dataclass
class ExportError:
    """Error information for failed export.

    Attributes:
        note_id: Database row ID.
        identifier: Note UUID.
        title: Note title.
        folder: Folder name.
        error: Error message.
    """

    note_id: int
    identifier: str
    title: str
    folder: str | None
    error: str


@dataclass
class FullExportResult:
    """Summary of full export operation.

    Attributes:
        output_dir: Directory where notes were exported.
        archive_path: Path to .7z archive if created.
        total_notes: Total number of notes processed.
        exported_count: Number successfully exported.
        locked_count: Number of locked notes (placeholders created).
        failed_count: Number of failed exports.
        total_attachments: Total attachments exported.
        folders: List of folder names.
        notes: List of individual note results.
        errors: List of export errors.
    """

    output_dir: Path
    archive_path: Path | None
    total_notes: int
    exported_count: int
    locked_count: int
    failed_count: int
    total_attachments: int
    folders: list[str]
    notes: list[NoteExportResult] = field(default_factory=list)
    errors: list[ExportError] = field(default_factory=list)
```

### Step 4: Run tests to verify they pass

```bash
uv run pytest tests/test_export.py -v
```

### Step 5: Commit

```bash
git add src/noted/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
feat(export): add data models for export operations

ExportOptions configures export behavior.
NoteExportResult tracks individual note outcomes.
FullExportResult aggregates export statistics.
EOF
)"
```

---

## Task 3: Add Locked Note Placeholder Generation

**Files:**
- Modify: `src/noted/export.py`
- Test: `tests/test_export.py`

### Step 1: Write failing test

Add to `tests/test_export.py`:

```python
from noted.models import Note
from datetime import datetime, UTC


def test_generate_locked_placeholder() -> None:
    """Test locked note placeholder content."""
    from noted.export import generate_locked_placeholder

    note = Note(
        id=55,
        identifier="LOCKED-UUID-123",
        title="Secret Note",
        folder="Personal",
        created=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        modified=datetime(2026, 1, 20, 14, 30, tzinfo=UTC),
    )

    content = generate_locked_placeholder(note)

    assert "# Secret Note" in content
    assert "locked" in content.lower()
    assert "LOCKED-UUID-123" in content
    assert "Personal" in content
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/test_export.py::test_generate_locked_placeholder -v
```

### Step 3: Implement function

Add to `src/noted/export.py`:

```python
from noted.models import Note


def generate_locked_placeholder(note: Note) -> str:
    """Generate markdown content for a locked note placeholder.

    Args:
        note: The locked note's metadata.

    Returns:
        Markdown content explaining the note is locked.
    """
    return f"""# {note.title}

> **This note is locked and cannot be exported.**
>
> To export this note, unlock it in Apple Notes and run the export again.

---
*Note ID: {note.id}*
*Identifier: {note.identifier}*
*Folder: {note.folder or "(No Folder)"}*
"""
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/test_export.py::test_generate_locked_placeholder -v
```

### Step 5: Commit

```bash
git add src/noted/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
feat(export): add locked note placeholder generation

Creates markdown file with explanation for locked notes.
EOF
)"
```

---

## Task 4: Add Unique Folder Name Generation

**Files:**
- Modify: `src/noted/export.py`
- Test: `tests/test_export.py`

### Step 1: Write failing tests

Add to `tests/test_export.py`:

```python
def test_make_unique_folder_name_no_conflict() -> None:
    """Test folder name generation without conflicts."""
    from noted.export import make_unique_folder_name

    used: set[str] = set()
    result = make_unique_folder_name("Meeting_Notes", "uuid-123", used)
    assert result == "Meeting_Notes"
    assert "Meeting_Notes" in used


def test_make_unique_folder_name_with_conflict() -> None:
    """Test folder name adds UUID suffix on conflict."""
    from noted.export import make_unique_folder_name

    used = {"Meeting_Notes"}
    result = make_unique_folder_name("Meeting_Notes", "abc123def456", used)
    assert result == "Meeting_Notes_abc123"
    assert "Meeting_Notes_abc123" in used
```

### Step 2: Implement function

Add to `src/noted/export.py`:

```python
def make_unique_folder_name(
    folder_name: str,
    identifier: str,
    used_names: set[str],
) -> str:
    """Generate a unique folder name, adding UUID suffix if needed.

    Args:
        folder_name: Desired folder name.
        identifier: Note UUID for suffix if conflict.
        used_names: Set of already-used names (modified in place).

    Returns:
        Unique folder name (original or with UUID suffix).
    """
    if folder_name not in used_names:
        used_names.add(folder_name)
        return folder_name

    # Add UUID suffix
    unique = f"{folder_name}_{identifier[:6]}"
    used_names.add(unique)
    return unique
```

### Step 3: Run tests

```bash
uv run pytest tests/test_export.py -k "unique_folder" -v
```

### Step 4: Commit

```bash
git add src/noted/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
feat(export): add unique folder name generation

Appends first 6 chars of UUID on name conflicts.
EOF
)"
```

---

## Task 5: Add Master Index Generation

**Files:**
- Modify: `src/noted/export.py`
- Test: `tests/test_export.py`

### Step 1: Write failing test

Add to `tests/test_export.py`:

```python
import json


def test_generate_master_index(tmp_path: Path) -> None:
    """Test master index.json generation."""
    from noted.export import (
        generate_master_index,
        FullExportResult,
        NoteExportResult,
        ExportError,
    )

    result = FullExportResult(
        output_dir=tmp_path,
        archive_path=None,
        total_notes=3,
        exported_count=2,
        locked_count=1,
        failed_count=0,
        total_attachments=5,
        folders=["Work", "Personal"],
        notes=[
            NoteExportResult(
                note_id=1,
                identifier="uuid-1",
                title="Note 1",
                folder="Work",
                status="success",
                path=Path("Work/Note_1/Note_1.md"),
                attachment_count=3,
                error=None,
            ),
            NoteExportResult(
                note_id=2,
                identifier="uuid-2",
                title="Locked",
                folder="Personal",
                status="locked",
                path=Path("Personal/Locked/Locked.md"),
                attachment_count=0,
                error=None,
            ),
        ],
        errors=[],
    )

    folder_info = [
        {"name": "Work", "path": "Work/", "note_count": 1},
        {"name": "Personal", "path": "Personal/", "note_count": 1},
    ]

    index_path = tmp_path / "index.json"
    generate_master_index(index_path, result, folder_info)

    assert index_path.exists()
    data = json.loads(index_path.read_text())

    assert data["export_version"] == "1.0"
    assert data["source"] == "Apple Notes"
    assert data["statistics"]["total_notes"] == 3
    assert data["statistics"]["exported_count"] == 2
    assert data["statistics"]["locked_count"] == 1
    assert len(data["folders"]) == 2
    assert len(data["notes"]) == 2
```

### Step 2: Implement function

Add to `src/noted/export.py`:

```python
import json
from datetime import UTC, datetime


def generate_master_index(
    index_path: Path,
    result: FullExportResult,
    folder_info: list[dict[str, str | int]],
) -> None:
    """Generate master index.json for full export.

    Args:
        index_path: Path to write index.json.
        result: Export result with statistics and note list.
        folder_info: List of folder info dicts with name, path, note_count.
    """
    notes_data = []
    for note_result in result.notes:
        notes_data.append({
            "id": note_result.note_id,
            "identifier": note_result.identifier,
            "title": note_result.title,
            "folder": note_result.folder,
            "path": str(note_result.path) if note_result.path else None,
            "attachment_count": note_result.attachment_count,
            "locked": note_result.status == "locked",
            "export_status": note_result.status,
        })

    errors_data = []
    for error in result.errors:
        errors_data.append({
            "note_id": error.note_id,
            "identifier": error.identifier,
            "title": error.title,
            "folder": error.folder,
            "error": error.error,
        })

    index = {
        "export_version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "source": "Apple Notes",
        "statistics": {
            "total_notes": result.total_notes,
            "exported_count": result.exported_count,
            "locked_count": result.locked_count,
            "failed_count": result.failed_count,
            "total_attachments": result.total_attachments,
            "total_folders": len(folder_info),
        },
        "folders": folder_info,
        "notes": notes_data,
        "errors": errors_data,
    }

    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
```

### Step 3: Run test

```bash
uv run pytest tests/test_export.py::test_generate_master_index -v
```

### Step 4: Commit

```bash
git add src/noted/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
feat(export): add master index generation

Creates index.json with export metadata, statistics, folder list,
note list, and any errors.
EOF
)"
```

---

## Task 6: Add Single Note Export Function

**Files:**
- Modify: `src/noted/export.py`
- Test: `tests/test_export.py`

### Step 1: Write failing test

Add to `tests/test_export.py`:

```python
import sqlite3


def test_export_single_note(tmp_path: Path) -> None:
    """Test exporting a single note to folder structure."""
    from noted.export import export_single_note
    from noted.models import Note

    # Create minimal test database
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)
    # Insert minimal gzipped protobuf (just text "Hello")
    import gzip
    note_proto = b"\x12\x05Hello"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)
    conn.execute(
        "INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (?, ?, ?)",
        (1, 1, compressed),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    note = Note(
        id=1,
        identifier="test-uuid",
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    output_dir = tmp_path / "export"
    result = export_single_note(conn, note, output_dir)

    conn.close()

    assert result.status == "success"
    assert result.path is not None

    # Check file was created
    note_file = output_dir / result.path
    assert note_file.exists()
    assert "Test Note" in note_file.read_text()
```

### Step 2: Implement function

Add to `src/noted/export.py`:

```python
import sqlite3

from noted import attachments, db, display, protobuf, tables
from noted.models import Note


def export_single_note(
    conn: sqlite3.Connection,
    note: Note,
    output_dir: Path,
    used_folder_names: set[str] | None = None,
) -> NoteExportResult:
    """Export a single note to the output directory.

    Creates a folder for the note containing the markdown file
    and attachments subdirectory.

    Args:
        conn: Database connection.
        note: Note to export.
        output_dir: Base output directory.
        used_folder_names: Set of already-used folder names for deduplication.

    Returns:
        NoteExportResult with export status and path.
    """
    if used_folder_names is None:
        used_folder_names = set()

    # Determine folder path
    folder_name = note.folder or "(No Folder)"
    folder_path = output_dir / attachments.sanitize_filename(folder_name)

    # Create note folder with unique name
    note_folder_name = attachments.sanitize_filename(note.title)
    note_folder_name = make_unique_folder_name(
        note_folder_name, note.identifier, used_folder_names
    )
    note_path = folder_path / note_folder_name

    # Get note content
    raw_data = db.get_note_content(conn, note.id)

    if raw_data is None:
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="failed",
            path=None,
            attachment_count=0,
            error="Note has no content",
        )

    # Check if locked
    if protobuf.is_note_locked(raw_data):
        # Create placeholder
        note_path.mkdir(parents=True, exist_ok=True)
        note_file = note_path / f"{note_folder_name}.md"
        note_file.write_text(generate_locked_placeholder(note), encoding="utf-8")

        relative_path = note_file.relative_to(output_dir)
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="locked",
            path=relative_path,
            attachment_count=0,
            error=None,
        )

    try:
        # Parse content
        attachment_names = db.get_attachment_names(conn, note.id)
        content = protobuf.parse_note_data(
            raw_data, attachment_names, include_formatting=True
        )

        # Parse table attachments
        if content.attachments:
            for attachment in content.attachments:
                if attachment.type_uti == "com.apple.notes.table":
                    result = db.get_table_data(conn, attachment.identifier)
                    if result:
                        table_data, summary = result
                        attachment.table = tables.parse_table_data(table_data, summary)

        # Generate markdown
        markdown_content = display.get_note_markdown(note, content)

        # Create note folder and write file
        note_path.mkdir(parents=True, exist_ok=True)
        note_file = note_path / f"{note_folder_name}.md"
        note_file.write_text(markdown_content, encoding="utf-8")

        # Export attachments
        attachment_count = 0
        if content.attachments:
            # For full export, attachments go in note_path/attachments/
            export_result = attachments.export_attachments(
                conn=conn,
                attachments=content.attachments,
                output_dir=note_path,
                base_name="attachments",
                note=note,
            )
            attachment_count = len(export_result.exported)

            # Rename attachments folder if created (remove "_attachments" suffix)
            old_att_dir = note_path / "attachments_attachments"
            new_att_dir = note_path / "attachments"
            if old_att_dir.exists() and not new_att_dir.exists():
                old_att_dir.rename(new_att_dir)

        relative_path = note_file.relative_to(output_dir)
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="success",
            path=relative_path,
            attachment_count=attachment_count,
            error=None,
        )

    except Exception as e:
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="failed",
            path=None,
            attachment_count=0,
            error=str(e),
        )
```

### Step 3: Run test

```bash
uv run pytest tests/test_export.py::test_export_single_note -v
```

### Step 4: Commit

```bash
git add src/noted/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
feat(export): add export_single_note function

Exports note to folder structure with markdown and attachments.
Handles locked notes with placeholder files.
EOF
)"
```

---

## Task 7: Add Full Export Function

**Files:**
- Modify: `src/noted/export.py`
- Test: `tests/test_export.py`

### Step 1: Write failing test

Add to `tests/test_export.py`:

```python
def test_export_all_notes(tmp_path: Path) -> None:
    """Test full export of all notes."""
    from noted.export import export_all_notes, ExportOptions

    # Create test database with multiple notes
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTITLE1 TEXT,
            ZTITLE2 TEXT,
            ZFOLDER INTEGER,
            ZCREATIONDATE REAL,
            ZMODIFICATIONDATE REAL,
            ZMARKEDFORDELETION INTEGER DEFAULT 0,
            ZTYPEUTI TEXT,
            ZTITLE TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)

    # Create folder
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "folder-1", None, "Work", None, 0, 0, 0, None, None),
    )

    # Create notes with minimal content
    import gzip
    note_proto = b"\x12\x05Hello"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (2, "note-1", "Note One", None, 1, 0, 0, 0, None, None),
    )
    conn.execute(
        "INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (?, ?, ?)",
        (1, 2, compressed),
    )

    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, "note-2", "Note Two", None, 1, 0, 0, 0, None, None),
    )
    conn.execute(
        "INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (?, ?, ?)",
        (2, 3, compressed),
    )

    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    output_dir = tmp_path / "notes_export"
    options = ExportOptions(output_dir=output_dir)

    result = export_all_notes(conn, options)

    conn.close()

    assert result.total_notes == 2
    assert result.exported_count == 2
    assert result.failed_count == 0
    assert output_dir.exists()
    assert (output_dir / "index.json").exists()
    assert (output_dir / "Work").exists()
```

### Step 2: Implement function

Add to `src/noted/export.py`:

```python
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn


def export_all_notes(
    conn: sqlite3.Connection,
    options: ExportOptions,
) -> FullExportResult:
    """Export all notes to structured folder hierarchy.

    Args:
        conn: Database connection.
        options: Export configuration.

    Returns:
        FullExportResult with statistics and note list.
    """
    # Get all notes
    notes = db.get_all_notes(
        conn,
        folder=options.folder_filter,
        include_deleted=options.include_deleted,
    )

    # Get folder info
    folders_raw = db.get_folders(conn)
    folder_names = [f.name for f in folders_raw]

    # Create output directory
    options.output_dir.mkdir(parents=True, exist_ok=True)

    # Track results
    note_results: list[NoteExportResult] = []
    errors: list[ExportError] = []
    total_attachments = 0
    exported_count = 0
    locked_count = 0
    failed_count = 0

    # Track used folder names per parent folder for deduplication
    used_names_by_folder: dict[str, set[str]] = {}

    # Export notes with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        disable=options.verbose,
    ) as progress:
        task = progress.add_task("Exporting notes...", total=len(notes))

        for note in notes:
            # Get or create used names set for this folder
            folder_key = note.folder or "(No Folder)"
            if folder_key not in used_names_by_folder:
                used_names_by_folder[folder_key] = set()

            result = export_single_note(
                conn, note, options.output_dir, used_names_by_folder[folder_key]
            )
            note_results.append(result)

            if result.status == "success":
                exported_count += 1
                total_attachments += result.attachment_count
                if options.verbose:
                    att_info = f" ({result.attachment_count} attachments)" if result.attachment_count else ""
                    print(f"  \u2713 {note.folder or '(No Folder)'}/{note.title}{att_info}")
            elif result.status == "locked":
                locked_count += 1
                if options.verbose:
                    print(f"  \u26a0 {note.folder or '(No Folder)'}/{note.title} (locked)")
            else:
                failed_count += 1
                errors.append(ExportError(
                    note_id=note.id,
                    identifier=note.identifier,
                    title=note.title,
                    folder=note.folder,
                    error=result.error or "Unknown error",
                ))
                if options.verbose:
                    print(f"  \u2717 {note.folder or '(No Folder)'}/{note.title} (failed: {result.error})")

            progress.update(task, advance=1)

    # Build folder info for index
    folder_info = []
    for folder_name in folder_names:
        folder_path = attachments.sanitize_filename(folder_name)
        count = sum(1 for r in note_results if r.folder == folder_name)
        if count > 0:
            folder_info.append({
                "name": folder_name,
                "path": f"{folder_path}/",
                "note_count": count,
            })

    # Add (No Folder) if any notes have no folder
    no_folder_count = sum(1 for r in note_results if r.folder is None)
    if no_folder_count > 0:
        folder_info.append({
            "name": "(No Folder)",
            "path": "(No_Folder)/",
            "note_count": no_folder_count,
        })

    # Build result
    result = FullExportResult(
        output_dir=options.output_dir,
        archive_path=None,
        total_notes=len(notes),
        exported_count=exported_count,
        locked_count=locked_count,
        failed_count=failed_count,
        total_attachments=total_attachments,
        folders=folder_names,
        notes=note_results,
        errors=errors,
    )

    # Generate master index
    index_path = options.output_dir / "index.json"
    generate_master_index(index_path, result, folder_info)

    # Create archive if requested
    if options.create_archive:
        archive_path = create_full_archive(options.output_dir)
        result.archive_path = archive_path

    return result


def create_full_archive(output_dir: Path) -> Path:
    """Create 7zip archive of the entire export.

    Unlike single-note archive, this keeps the original files.

    Args:
        output_dir: Directory to archive.

    Returns:
        Path to created .7z archive.
    """
    import py7zr

    archive_path = output_dir.with_suffix(".7z")

    with py7zr.SevenZipFile(archive_path, "w") as archive:
        for file in output_dir.rglob("*"):
            if file.is_file():
                arcname = str(file.relative_to(output_dir.parent))
                archive.write(file, arcname)

    return archive_path
```

### Step 3: Run test

```bash
uv run pytest tests/test_export.py::test_export_all_notes -v
```

### Step 4: Commit

```bash
git add src/noted/export.py tests/test_export.py
git commit -m "$(cat <<'EOF'
feat(export): add export_all_notes function

Exports all notes to folder hierarchy with progress bar.
Generates master index.json.
Optionally creates 7zip archive.
EOF
)"
```

---

## Task 8: Add CLI Export Command

**Files:**
- Modify: `src/noted/cli.py`
- Test: `tests/test_cli.py`

### Step 1: Write failing tests

Add to `tests/test_cli.py`:

```python
def test_export_command_help() -> None:
    """Test export command has help text."""
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "Export notes" in result.output
    assert "--all" in result.output


def test_export_requires_all_or_note_id() -> None:
    """Test export requires either --all or note_id."""
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 1
    assert "either" in result.output.lower() or "required" in result.output.lower()


def test_export_all_flag(tmp_path: Path) -> None:
    """Test --all flag triggers full export."""
    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.export_module.export_all_notes") as mock_export,
    ):
        mock_result = MagicMock()
        mock_result.total_notes = 10
        mock_result.exported_count = 9
        mock_result.locked_count = 1
        mock_result.failed_count = 0
        mock_result.total_attachments = 5
        mock_result.output_dir = tmp_path / "notes_export"
        mock_result.archive_path = None
        mock_export.return_value = mock_result

        result = runner.invoke(app, ["export", "--all", "-o", str(tmp_path / "notes_export")])

        assert result.exit_code == 0
        mock_export.assert_called_once()
```

### Step 2: Implement export command

Add to `src/noted/cli.py` after the `view` command:

```python
from noted import export as export_module


@app.command()
def export(
    note_ref: str | None = typer.Argument(
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
        help="Output directory.",
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
    # Validate: need either --all or note_ref
    if not all_notes and note_ref is None:
        display.display_error("Specify either --all or a note ID/UUID to export.")
        raise typer.Exit(code=1)

    if all_notes and note_ref is not None:
        display.display_error("Cannot use --all with a specific note ID.")
        raise typer.Exit(code=1)

    try:
        conn = db.get_connection()

        if all_notes:
            # Full export
            options = export_module.ExportOptions(
                output_dir=output,
                include_deleted=not exclude_deleted,
                create_archive=zip_archive,
                folder_filter=folder_filter,
                verbose=verbose,
            )

            result = export_module.export_all_notes(conn, options)
            conn.close()

            # Display summary
            display.display_success(f"Exported {result.exported_count} notes to {result.output_dir}")
            if result.locked_count > 0:
                display.display_warning(f"{result.locked_count} locked notes (placeholders created)")
            if result.failed_count > 0:
                display.display_error(f"{result.failed_count} notes failed (see index.json)")
            if result.total_attachments > 0:
                console.print(f"[dim]Total attachments: {result.total_attachments}[/dim]")
            if result.archive_path:
                display.display_success(f"Created archive: {result.archive_path}")

        else:
            # Single note export
            note = db.get_note(conn, note_ref)
            if note is None:
                display.display_error(f"Note '{note_ref}' not found.")
                conn.close()
                raise typer.Exit(code=1)

            # Use flat structure for single note (like view --attachments)
            from noted import attachments as att_module

            base_name = att_module.sanitize_filename(note.title)
            base_path = output.parent / base_name if output.name == "notes_export" else output

            # Get note content
            raw_data = db.get_note_content(conn, note.id)
            if raw_data is None:
                conn.close()
                display.display_error("Note has no content.")
                raise typer.Exit(code=1)

            if protobuf.is_note_locked(raw_data):
                conn.close()
                display.display_error("Note is locked and cannot be exported.")
                raise typer.Exit(code=1)

            # Parse and export
            attachment_names = db.get_attachment_names(conn, note.id)
            content = protobuf.parse_note_data(raw_data, attachment_names, include_formatting=True)

            if content.attachments:
                for attachment in content.attachments:
                    if attachment.type_uti == "com.apple.notes.table":
                        result = db.get_table_data(conn, attachment.identifier)
                        if result:
                            table_data, summary = result
                            attachment.table = tables.parse_table_data(table_data, summary)

            # Write markdown
            markdown = display.get_note_markdown(note, content)
            note_path = base_path.with_suffix(".md")
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(markdown, encoding="utf-8")

            # Export attachments
            export_result = att_module.AttachmentExportResult(
                exported=[], skipped=[], manifest_path=None, attachments_dir=None
            )
            if content.attachments:
                export_result = att_module.export_attachments(
                    conn=conn,
                    attachments=content.attachments,
                    output_dir=base_path.parent,
                    base_name=base_name,
                    note=note,
                )

            conn.close()

            # Create archive if requested
            if zip_archive:
                archive_path = att_module.create_archive(
                    base_path, note_path, export_result.attachments_dir
                )
                display.display_success(f"Created archive: {archive_path}")
            else:
                display.display_success(f"Exported to {note_path}")

            if export_result.exported:
                display.display_success(f"Exported {len(export_result.exported)} attachments")
            if export_result.skipped:
                from collections import Counter
                type_counts = Counter(
                    protobuf.UTI_TYPE_MAP.get(a.type_uti, "Unknown") for a in export_result.skipped
                )
                summary = ", ".join(f"{v} {k}" for k, v in type_counts.items())
                display.display_warning(f"Skipped {len(export_result.skipped)} non-exportable: {summary}")

    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Error exporting notes")
        display.display_error(str(e))
        raise typer.Exit(code=1)
```

### Step 3: Run tests

```bash
uv run pytest tests/test_cli.py -k "export" -v
```

### Step 4: Commit

```bash
git add src/noted/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): add export command

Supports --all for full export and single note by ID/UUID.
Options: --zip, --folder, --exclude-deleted, --verbose.
EOF
)"
```

---

## Task 9: Remove --attachments and --zip from view Command

**Files:**
- Modify: `src/noted/cli.py`
- Modify: `tests/test_cli.py`

### Step 1: Remove flags from view command

Edit `src/noted/cli.py` to remove `attachments_flag` and `zip_archive` parameters from the `view` function, and remove all code that references them (the entire `if attachments_flag:` block).

The `view` command should only support:
- `--markdown` / `-md`
- `--json` / `-j`
- `--json-styled`
- `--html`
- `--export` / `-o`

### Step 2: Update tests

Remove tests that reference `--attachments` or `--zip` on the `view` command.

### Step 3: Run tests

```bash
uv run pytest tests/test_cli.py -v
```

### Step 4: Commit

```bash
git add src/noted/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
refactor(cli): remove --attachments and --zip from view command

These options are now available via the export command.
view command returns to its core purpose: display/output note content.
EOF
)"
```

---

## Task 10: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

### Step 1: Update quick start examples

Replace attachment export examples with new `export` command:

```markdown
# Export all notes
uv run noted export --all

# Export all notes with 7zip archive
uv run noted export --all --zip

# Export to custom directory
uv run noted export --all -o ~/Backups/notes_2026-01-29

# Export single note
uv run noted export 42
uv run noted export "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"

# Export with archive
uv run noted export 42 --zip

# Export only Work folder
uv run noted export --all --folder "Work"

# Exclude deleted notes
uv run noted export --all --exclude-deleted

# Verbose output
uv run noted export --all --verbose
```

### Step 2: Update package structure

Add `export.py` to the file list and update `cli.py` description.

### Step 3: Commit

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: update CLAUDE.md for new export command

Replace view --attachments examples with export command.
Add export.py to package structure.
EOF
)"
```

---

## Task 11: Run Full Test Suite and Type Checking

**Files:**
- All modified files

### Step 1: Run full test suite

```bash
uv run pytest -v
```

### Step 2: Run linting

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### Step 3: Run type checking

```bash
uv run pyrefly check
```

### Step 4: Fix any issues

### Step 5: Commit fixes if any

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix: resolve test, lint, and type issues
EOF
)"
```

---

## Task 12: Manual Integration Test

### Step 1: Test full export

```bash
uv run noted export --all -o /tmp/test_export
```

Verify:
- Creates `/tmp/test_export/` directory
- Creates `index.json` at root
- Creates folder subdirectories matching Apple Notes folders
- Each note has its own folder with `.md` file
- Notes with attachments have `attachments/` subdirectory

### Step 2: Test with archive

```bash
uv run noted export --all --zip -o /tmp/test_export_2
```

Verify:
- Creates both folder structure AND `.7z` archive
- Archive contains full hierarchy

### Step 3: Test single note export

```bash
uv run noted export <note_id> -o /tmp/single_note
```

Verify:
- Creates flat structure: `Note_Title.md` + `Note_Title_attachments/`

### Step 4: Test filtering

```bash
uv run noted export --all --folder "Work" -o /tmp/work_only
uv run noted export --all --exclude-deleted -o /tmp/no_deleted
```

### Step 5: Test verbose mode

```bash
uv run noted export --all --verbose
```

Verify shows each note as it's exported.

---

## Summary

After completing all tasks, the `noted` CLI will have:

1. **New `export` command** with:
   - `--all` flag for full export
   - Single note export by ID/UUID
   - `--zip` for 7zip archive
   - `--folder` filter
   - `--exclude-deleted` option
   - `--verbose` for detailed output

2. **Structured full export** with:
   - Master `index.json`
   - Folder hierarchy matching Apple Notes
   - Per-note folders with markdown and attachments
   - Locked note placeholders

3. **Clean `view` command** focused on display/output only

4. **Updated documentation** in CLAUDE.md
