# Attachment Export Implementation Plan

> **Status:** ✅ COMPLETED (2026-01-29)

**Goal:** Add `--attachments` and `--zip` flags to the `view` command to export note attachments alongside the note file.

**Architecture:** New `attachments.py` module handles extraction, file writing, manifest generation, and 7zip archiving. Database layer gets a new function to fetch attachment binary data from disk. CLI integrates these with two new flags.

**Tech Stack:** Python 3.14+, py7zr for 7zip compression, existing sqlite3/typer/rich stack.

## Implementation Notes

> **Critical Discovery:** During implementation of Task 2, we discovered that Apple Notes stores
> attachments as **files on disk**, not in the SQLite database. The original plan assumed a `ZDATA`
> column in `ZICCLOUDSYNCINGOBJECT`, but attachments are actually stored at:
> `~/Library/Group Containers/group.com.apple.notes/Accounts/<ACCOUNT>/Media/<MEDIA_ID>/<subfolder>/<filename>`
>
> The implementation was corrected to:
> 1. Query the ZMEDIA foreign key to get the media record
> 2. Use the media record's ZIDENTIFIER and ZFILENAME to locate the file on disk
> 3. Read the file contents from the file system
>
> See `docs/apple-notes-attachment-structure.md` for full documentation of this structure.

---

### Task 1: Add py7zr Dependency

**Files:**
- Modify: `pyproject.toml:6-11`

**Step 1: Add the dependency**

Edit `pyproject.toml` to add py7zr to dependencies:

```toml
dependencies = [
    "typer>=0.15",
    "rich>=13",
    "loguru>=0.7",
    "betterproto>=2.0.0b6",
    "py7zr>=0.20.0",
]
```

**Step 2: Install dependencies**

Run: `uv sync`
Expected: Successfully installs py7zr

**Step 3: Verify installation**

Run: `uv run python -c "import py7zr; print(py7zr.__version__)"`
Expected: Prints version number (e.g., "0.22.0")

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
chore: add py7zr dependency for 7zip compression
EOF
)"
```

---

### Task 2: Add get_attachment_data Function to db.py

**Files:**
- Modify: `src/noted/db.py:344` (add at end)
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_get_attachment_data(tmp_path: Path) -> None:
    """Test fetching attachment binary data by identifier."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)

    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)

    test_data = b"\x89PNG\r\n\x1a\nfake_image_data"
    conn.execute(
        """INSERT INTO ZICCLOUDSYNCINGOBJECT
           (Z_PK, ZIDENTIFIER, ZTYPEUTI, ZTITLE, ZDATA)
           VALUES (?, ?, ?, ?, ?)""",
        (1, "test-uuid-123", "public.png", "photo.png", test_data),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    from noted.db import get_attachment_data
    result = get_attachment_data(conn, "test-uuid-123")
    assert result is not None
    assert result[0] == test_data
    assert result[1] == "public.png"
    assert result[2] == "photo.png"
    conn.close()


def test_get_attachment_data_not_found(tmp_path: Path) -> None:
    """Test fetching attachment data for non-existent identifier."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    from noted.db import get_attachment_data
    result = get_attachment_data(conn, "nonexistent")
    assert result is None
    conn.close()


def test_get_attachment_data_no_binary(tmp_path: Path) -> None:
    """Test that attachments without ZDATA return None."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)

    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)

    # Insert attachment without binary data (like a table)
    conn.execute(
        """INSERT INTO ZICCLOUDSYNCINGOBJECT
           (Z_PK, ZIDENTIFIER, ZTYPEUTI, ZTITLE, ZDATA)
           VALUES (?, ?, ?, ?, ?)""",
        (1, "table-uuid", "com.apple.notes.table", None, None),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    from noted.db import get_attachment_data
    result = get_attachment_data(conn, "table-uuid")
    assert result is None
    conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_attachment_data -v`
Expected: FAIL with "cannot import name 'get_attachment_data'"

**Step 3: Write minimal implementation**

Add to `src/noted/db.py` at the end:

```python
def get_attachment_data(
    conn: sqlite3.Connection,
    identifier: str,
) -> tuple[bytes, str, str | None] | None:
    """Fetch binary data for an attachment by identifier.

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
    cursor = conn.execute(query, (identifier,))
    row = cursor.fetchone()
    if row is None:
        return None
    return (row["ZDATA"], row["ZTYPEUTI"], row["ZTITLE"])
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py::test_get_attachment_data tests/test_db.py::test_get_attachment_data_not_found tests/test_db.py::test_get_attachment_data_no_binary -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): add get_attachment_data function

Fetches binary data, UTI, and title for attachments by identifier.
Returns None for attachments without binary data (tables, links, etc).
EOF
)"
```

---

### Task 3: Create attachments.py Module with Data Models

**Files:**
- Create: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test for data models**

Create `tests/test_attachments.py`:

```python
"""Tests for noted.attachments."""

from noted.attachments import ExportedAttachment, AttachmentExportResult


def test_exported_attachment_exported() -> None:
    """Test ExportedAttachment for successfully exported file."""
    att = ExportedAttachment(
        identifier="uuid-123",
        filename="photo.jpg",
        type_uti="public.jpeg",
        exported=True,
        skip_reason=None,
    )
    assert att.identifier == "uuid-123"
    assert att.filename == "photo.jpg"
    assert att.exported is True
    assert att.skip_reason is None


def test_exported_attachment_skipped() -> None:
    """Test ExportedAttachment for skipped file."""
    att = ExportedAttachment(
        identifier="uuid-456",
        filename=None,
        type_uti="com.apple.notes.table",
        exported=False,
        skip_reason="Rendered inline in note content",
    )
    assert att.exported is False
    assert att.skip_reason == "Rendered inline in note content"


def test_attachment_export_result() -> None:
    """Test AttachmentExportResult aggregates exports and skips."""
    exported = [
        ExportedAttachment("id1", "a.jpg", "public.jpeg", True, None),
    ]
    skipped = [
        ExportedAttachment("id2", None, "com.apple.notes.table", False, "No binary data"),
    ]
    result = AttachmentExportResult(
        exported=exported,
        skipped=skipped,
        manifest_path=None,
        attachments_dir=None,
    )
    assert len(result.exported) == 1
    assert len(result.skipped) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_exported_attachment_exported -v`
Expected: FAIL with "No module named 'noted.attachments'"

**Step 3: Write minimal implementation**

Create `src/noted/attachments.py`:

```python
"""Attachment export functionality for Apple Notes.

Handles extracting attachments from notes and exporting them to disk,
with optional 7zip compression.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExportedAttachment:
    """Result of exporting a single attachment.

    Attributes:
        identifier: Unique identifier (UUID) for the attachment.
        filename: Final filename used (after deduplication), or None if skipped.
        type_uti: Uniform Type Identifier (e.g., 'public.jpeg').
        exported: True if binary data was written to disk.
        skip_reason: Why it wasn't exported, or None if exported successfully.
    """

    identifier: str
    filename: str | None
    type_uti: str
    exported: bool
    skip_reason: str | None


@dataclass
class AttachmentExportResult:
    """Summary of attachment export operation.

    Attributes:
        exported: List of successfully exported attachments.
        skipped: List of attachments that were skipped.
        manifest_path: Path to manifest.json, or None if no attachments.
        attachments_dir: Path to attachments directory, or None if no attachments.
    """

    exported: list[ExportedAttachment]
    skipped: list[ExportedAttachment]
    manifest_path: Path | None
    attachments_dir: Path | None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add data models for attachment export

ExportedAttachment tracks individual export results.
AttachmentExportResult aggregates exported/skipped lists.
EOF
)"
```

---

### Task 4: Add UTI to File Extension Mapping

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
from noted.attachments import uti_to_extension


def test_uti_to_extension_jpeg() -> None:
    """Test UTI to extension for JPEG images."""
    assert uti_to_extension("public.jpeg") == ".jpg"


def test_uti_to_extension_png() -> None:
    """Test UTI to extension for PNG images."""
    assert uti_to_extension("public.png") == ".png"


def test_uti_to_extension_pdf() -> None:
    """Test UTI to extension for PDF documents."""
    assert uti_to_extension("com.adobe.pdf") == ".pdf"
    assert uti_to_extension("public.pdf") == ".pdf"


def test_uti_to_extension_unknown() -> None:
    """Test UTI to extension for unknown types returns .bin."""
    assert uti_to_extension("com.unknown.type") == ".bin"


def test_uti_to_extension_drawing() -> None:
    """Test UTI to extension for Apple drawings."""
    assert uti_to_extension("com.apple.drawing") == ".png"
    assert uti_to_extension("com.apple.drawing.2") == ".png"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_uti_to_extension_jpeg -v`
Expected: FAIL with "cannot import name 'uti_to_extension'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
# UTI to file extension mapping
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


def uti_to_extension(uti: str) -> str:
    """Convert UTI to file extension.

    Args:
        uti: Uniform Type Identifier (e.g., 'public.jpeg').

    Returns:
        File extension with leading dot (e.g., '.jpg').
        Returns '.bin' for unknown types.
    """
    return UTI_EXTENSION_MAP.get(uti, ".bin")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py::test_uti_to_extension_jpeg tests/test_attachments.py::test_uti_to_extension_png tests/test_attachments.py::test_uti_to_extension_pdf tests/test_attachments.py::test_uti_to_extension_unknown tests/test_attachments.py::test_uti_to_extension_drawing -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add UTI to file extension mapping

Maps Apple UTI types to standard file extensions.
Returns .bin for unknown types.
EOF
)"
```

---

### Task 5: Add Filename Sanitization

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
from noted.attachments import sanitize_filename


def test_sanitize_filename_simple() -> None:
    """Test sanitize_filename with normal filename."""
    assert sanitize_filename("photo.jpg") == "photo.jpg"


def test_sanitize_filename_spaces() -> None:
    """Test sanitize_filename replaces spaces with underscores."""
    assert sanitize_filename("my photo.jpg") == "my_photo.jpg"


def test_sanitize_filename_special_chars() -> None:
    """Test sanitize_filename removes special characters."""
    assert sanitize_filename("file/with:bad*chars?.jpg") == "filewithbadchars.jpg"


def test_sanitize_filename_unicode() -> None:
    """Test sanitize_filename handles unicode."""
    assert sanitize_filename("café_photo.jpg") == "café_photo.jpg"


def test_sanitize_filename_empty() -> None:
    """Test sanitize_filename with empty string."""
    assert sanitize_filename("") == "attachment"


def test_sanitize_filename_only_bad_chars() -> None:
    """Test sanitize_filename with only bad characters."""
    assert sanitize_filename("***") == "attachment"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_sanitize_filename_simple -v`
Expected: FAIL with "cannot import name 'sanitize_filename'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
import re


def sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe filesystem use.

    Removes or replaces characters that are invalid in filenames
    on common operating systems (Windows, macOS, Linux).

    Args:
        name: Original filename.

    Returns:
        Sanitized filename safe for filesystem use.
    """
    if not name:
        return "attachment"

    # Replace spaces with underscores
    result = name.replace(" ", "_")

    # Remove characters invalid on Windows/macOS/Linux
    # Invalid: / \ : * ? " < > |
    result = re.sub(r'[/\\:*?"<>|]', "", result)

    # Remove control characters
    result = re.sub(r"[\x00-\x1f\x7f]", "", result)

    # If nothing left, use default
    if not result or result.strip(".") == "":
        return "attachment"

    return result
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py -k "sanitize" -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add filename sanitization

Removes invalid filesystem characters and replaces spaces.
Returns 'attachment' for empty or all-invalid inputs.
EOF
)"
```

---

### Task 6: Add Unique Filename Generation

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
from noted.attachments import make_unique_filename


def test_make_unique_filename_no_conflict() -> None:
    """Test make_unique_filename when no conflict exists."""
    used: set[str] = set()
    result = make_unique_filename("photo.jpg", "uuid-123", used)
    assert result == "photo.jpg"
    assert "photo.jpg" in used


def test_make_unique_filename_with_conflict() -> None:
    """Test make_unique_filename adds UUID suffix on conflict."""
    used = {"photo.jpg"}
    result = make_unique_filename("photo.jpg", "abc123def456", used)
    assert result == "photo_abc123.jpg"
    assert "photo_abc123.jpg" in used


def test_make_unique_filename_no_extension() -> None:
    """Test make_unique_filename handles files without extension."""
    used = {"README"}
    result = make_unique_filename("README", "xyz789", used)
    assert result == "README_xyz789"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_make_unique_filename_no_conflict -v`
Expected: FAIL with "cannot import name 'make_unique_filename'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
def make_unique_filename(
    filename: str,
    identifier: str,
    used_names: set[str],
) -> str:
    """Generate a unique filename, adding UUID suffix if needed.

    Args:
        filename: Desired filename.
        identifier: Attachment UUID for suffix if conflict.
        used_names: Set of already-used filenames (modified in place).

    Returns:
        Unique filename (original or with UUID suffix).
    """
    if filename not in used_names:
        used_names.add(filename)
        return filename

    # Split into name and extension
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        unique = f"{name}_{identifier[:6]}.{ext}"
    else:
        unique = f"{filename}_{identifier[:6]}"

    used_names.add(unique)
    return unique
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py -k "unique" -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add unique filename generation

Appends first 6 chars of UUID when filename conflicts.
Tracks used names to prevent duplicates.
EOF
)"
```

---

### Task 7: Add Non-Exportable UTI Detection

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
from noted.attachments import get_skip_reason


def test_get_skip_reason_table() -> None:
    """Test skip reason for table attachments."""
    reason = get_skip_reason("com.apple.notes.table")
    assert reason == "Rendered inline in note content"


def test_get_skip_reason_link() -> None:
    """Test skip reason for URL links."""
    reason = get_skip_reason("public.url")
    assert reason == "URL link, no file data"


def test_get_skip_reason_map() -> None:
    """Test skip reason for map attachments."""
    reason = get_skip_reason("com.apple.mapkit.map-item")
    assert reason == "Location data, no file data"


def test_get_skip_reason_exportable() -> None:
    """Test skip reason is None for exportable types."""
    assert get_skip_reason("public.jpeg") is None
    assert get_skip_reason("public.png") is None
    assert get_skip_reason("com.adobe.pdf") is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_get_skip_reason_table -v`
Expected: FAIL with "cannot import name 'get_skip_reason'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
# UTIs that don't have exportable binary data
NON_EXPORTABLE_UTIS: dict[str, str] = {
    "com.apple.notes.table": "Rendered inline in note content",
    "com.apple.notes.gallery": "Gallery container, no single file",
    "com.apple.notes.inlinetextattachment": "Inline text, no file data",
    "com.apple.notes.inlinetextattachment.hashtag": "Hashtag, no file data",
    "com.apple.notes.inlinetextattachment.mention": "Mention, no file data",
    "public.url": "URL link, no file data",
    "com.apple.mapkit.map-item": "Location data, no file data",
    "public.vcard": "Contact data, no file data",
}


def get_skip_reason(type_uti: str) -> str | None:
    """Get skip reason for non-exportable attachment types.

    Args:
        type_uti: Uniform Type Identifier.

    Returns:
        Reason string if attachment should be skipped, None if exportable.
    """
    return NON_EXPORTABLE_UTIS.get(type_uti)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py -k "skip_reason" -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add non-exportable UTI detection

Identifies attachment types without binary data (tables, links, maps).
Returns human-readable skip reason for manifest.
EOF
)"
```

---

### Task 8: Add Manifest Generation

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
import json
from pathlib import Path

from noted.attachments import generate_manifest, ExportedAttachment


def test_generate_manifest(tmp_path: Path) -> None:
    """Test manifest generation with exported and skipped attachments."""
    exported = [
        ExportedAttachment("uuid-1", "photo.jpg", "public.jpeg", True, None),
        ExportedAttachment("uuid-2", "doc.pdf", "com.adobe.pdf", True, None),
    ]
    skipped = [
        ExportedAttachment("uuid-3", None, "com.apple.notes.table", False, "Rendered inline"),
    ]

    manifest_path = tmp_path / "manifest.json"
    generate_manifest(
        manifest_path,
        note_id=42,
        note_title="Test Note",
        exported=exported,
        skipped=skipped,
    )

    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())

    assert data["note_id"] == 42
    assert data["note_title"] == "Test Note"
    assert "exported_at" in data
    assert len(data["attachments"]) == 3

    # Check exported attachment
    att1 = data["attachments"][0]
    assert att1["identifier"] == "uuid-1"
    assert att1["filename"] == "photo.jpg"
    assert att1["exported"] is True

    # Check skipped attachment
    att3 = data["attachments"][2]
    assert att3["identifier"] == "uuid-3"
    assert att3["filename"] is None
    assert att3["exported"] is False
    assert att3["skip_reason"] == "Rendered inline"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_generate_manifest -v`
Expected: FAIL with "cannot import name 'generate_manifest'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
import json
from datetime import UTC, datetime


def generate_manifest(
    manifest_path: Path,
    note_id: int,
    note_title: str,
    exported: list[ExportedAttachment],
    skipped: list[ExportedAttachment],
) -> None:
    """Generate manifest.json for exported attachments.

    Args:
        manifest_path: Path to write manifest.json.
        note_id: The note's database ID.
        note_title: The note's title.
        exported: List of successfully exported attachments.
        skipped: List of skipped attachments.
    """
    # Combine exported and skipped, maintaining order
    all_attachments = []
    for att in exported:
        all_attachments.append({
            "identifier": att.identifier,
            "filename": att.filename,
            "type_uti": att.type_uti,
            "exported": att.exported,
        })
    for att in skipped:
        all_attachments.append({
            "identifier": att.identifier,
            "filename": att.filename,
            "type_uti": att.type_uti,
            "exported": att.exported,
            "skip_reason": att.skip_reason,
        })

    manifest = {
        "note_id": note_id,
        "note_title": note_title,
        "exported_at": datetime.now(UTC).isoformat(),
        "attachments": all_attachments,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py::test_generate_manifest -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add manifest generation

Creates manifest.json with note metadata and all attachment info.
Includes exported and skipped attachments with reasons.
EOF
)"
```

---

### Task 9: Add export_attachments Function

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
import sqlite3

from noted.attachments import export_attachments
from noted.models import Attachment


def test_export_attachments_single_image(tmp_path: Path) -> None:
    """Test exporting a single image attachment."""
    # Set up test database
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)
    image_data = b"\x89PNG\r\n\x1a\nfake_png_data"
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?)",
        (1, "img-uuid", "public.png", "photo.png", image_data),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    attachments = [
        Attachment(identifier="img-uuid", type_uti="public.png", title="photo.png"),
    ]

    result = export_attachments(
        conn=conn,
        attachments=attachments,
        output_dir=tmp_path,
        base_name="TestNote",
        note_id=1,
        note_title="Test Note",
    )

    conn.close()

    # Verify results
    assert len(result.exported) == 1
    assert len(result.skipped) == 0
    assert result.attachments_dir is not None
    assert result.attachments_dir.exists()

    # Check exported file
    exported_file = result.attachments_dir / "photo.png"
    assert exported_file.exists()
    assert exported_file.read_bytes() == image_data

    # Check manifest
    assert result.manifest_path is not None
    assert result.manifest_path.exists()


def test_export_attachments_skips_tables(tmp_path: Path) -> None:
    """Test that table attachments are skipped."""
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT,
            ZTYPEUTI TEXT,
            ZTITLE TEXT,
            ZDATA BLOB
        )
    """)
    # Table has no ZDATA
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?, ?, ?, ?, ?)",
        (1, "table-uuid", "com.apple.notes.table", None, None),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    attachments = [
        Attachment(identifier="table-uuid", type_uti="com.apple.notes.table"),
    ]

    result = export_attachments(
        conn=conn,
        attachments=attachments,
        output_dir=tmp_path,
        base_name="TestNote",
        note_id=1,
        note_title="Test Note",
    )

    conn.close()

    assert len(result.exported) == 0
    assert len(result.skipped) == 1
    assert result.skipped[0].skip_reason is not None


def test_export_attachments_empty_list(tmp_path: Path) -> None:
    """Test export with empty attachment list."""
    test_db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZIDENTIFIER TEXT
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = export_attachments(
        conn=conn,
        attachments=[],
        output_dir=tmp_path,
        base_name="TestNote",
        note_id=1,
        note_title="Test Note",
    )

    conn.close()

    assert len(result.exported) == 0
    assert len(result.skipped) == 0
    assert result.attachments_dir is None
    assert result.manifest_path is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_export_attachments_single_image -v`
Expected: FAIL with "cannot import name 'export_attachments'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
import sqlite3

from noted.models import Attachment
from noted import db


def export_attachments(
    conn: sqlite3.Connection,
    attachments: list[Attachment],
    output_dir: Path,
    base_name: str,
    note_id: int,
    note_title: str,
) -> AttachmentExportResult:
    """Export all attachments for a note to disk.

    Creates {base_name}_attachments/ directory containing:
    - Binary files for exportable attachments
    - manifest.json listing all attachments

    Args:
        conn: Database connection.
        attachments: List of attachments from note content.
        output_dir: Parent directory for output.
        base_name: Base name for attachments directory.
        note_id: Note's database ID for manifest.
        note_title: Note's title for manifest.

    Returns:
        AttachmentExportResult with lists of exported/skipped attachments.
    """
    if not attachments:
        return AttachmentExportResult(
            exported=[],
            skipped=[],
            manifest_path=None,
            attachments_dir=None,
        )

    exported: list[ExportedAttachment] = []
    skipped: list[ExportedAttachment] = []
    used_names: set[str] = set()

    # Create attachments directory
    attachments_dir = output_dir / f"{base_name}_attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    for att in attachments:
        # Check if this type is exportable
        skip_reason = get_skip_reason(att.type_uti)
        if skip_reason:
            skipped.append(ExportedAttachment(
                identifier=att.identifier,
                filename=None,
                type_uti=att.type_uti,
                exported=False,
                skip_reason=skip_reason,
            ))
            continue

        # Fetch binary data
        data = db.get_attachment_data(conn, att.identifier)
        if data is None:
            skipped.append(ExportedAttachment(
                identifier=att.identifier,
                filename=None,
                type_uti=att.type_uti,
                exported=False,
                skip_reason="No binary data in database",
            ))
            continue

        binary_data, type_uti, db_title = data

        # Determine filename
        title = att.title or db_title
        if title:
            filename = sanitize_filename(title)
        else:
            # Generate from UTI
            ext = uti_to_extension(type_uti)
            filename = f"attachment{ext}"

        # Ensure extension
        if "." not in filename:
            filename += uti_to_extension(type_uti)

        # Make unique
        filename = make_unique_filename(filename, att.identifier, used_names)

        # Write file
        file_path = attachments_dir / filename
        file_path.write_bytes(binary_data)

        exported.append(ExportedAttachment(
            identifier=att.identifier,
            filename=filename,
            type_uti=att.type_uti,
            exported=True,
            skip_reason=None,
        ))

    # Generate manifest
    manifest_path = attachments_dir / "manifest.json"
    generate_manifest(manifest_path, note_id, note_title, exported, skipped)

    return AttachmentExportResult(
        exported=exported,
        skipped=skipped,
        manifest_path=manifest_path,
        attachments_dir=attachments_dir,
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py -k "export_attachments" -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add export_attachments function

Exports attachment binary data to disk with manifest.
Handles filename conflicts, skips non-exportable types.
EOF
)"
```

---

### Task 10: Add Archive Creation

**Files:**
- Modify: `src/noted/attachments.py`
- Test: `tests/test_attachments.py`

**Step 1: Write the failing test**

Add to `tests/test_attachments.py`:

```python
import py7zr

from noted.attachments import create_archive


def test_create_archive(tmp_path: Path) -> None:
    """Test creating 7zip archive from note and attachments."""
    # Create note file
    note_file = tmp_path / "TestNote.md"
    note_file.write_text("# Test Note\n\nContent here.")

    # Create attachments directory
    att_dir = tmp_path / "TestNote_attachments"
    att_dir.mkdir()
    (att_dir / "photo.jpg").write_bytes(b"fake_image")
    (att_dir / "manifest.json").write_text('{"note_id": 1}')

    # Create archive
    archive_path = create_archive(
        base_path=tmp_path / "TestNote",
        note_file=note_file,
        attachments_dir=att_dir,
    )

    # Verify archive exists
    assert archive_path.exists()
    assert archive_path.suffix == ".7z"

    # Verify contents
    with py7zr.SevenZipFile(archive_path, "r") as archive:
        names = archive.getnames()
        assert "TestNote.md" in names
        assert "TestNote_attachments/photo.jpg" in names
        assert "TestNote_attachments/manifest.json" in names

    # Verify originals cleaned up
    assert not note_file.exists()
    assert not att_dir.exists()


def test_create_archive_no_attachments(tmp_path: Path) -> None:
    """Test creating archive with note only, no attachments."""
    note_file = tmp_path / "TestNote.md"
    note_file.write_text("# Test Note")

    archive_path = create_archive(
        base_path=tmp_path / "TestNote",
        note_file=note_file,
        attachments_dir=None,
    )

    assert archive_path.exists()
    with py7zr.SevenZipFile(archive_path, "r") as archive:
        names = archive.getnames()
        assert "TestNote.md" in names
        assert len(names) == 1

    assert not note_file.exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_attachments.py::test_create_archive -v`
Expected: FAIL with "cannot import name 'create_archive'"

**Step 3: Write minimal implementation**

Add to `src/noted/attachments.py`:

```python
import shutil

import py7zr


def create_archive(
    base_path: Path,
    note_file: Path,
    attachments_dir: Path | None,
) -> Path:
    """Create 7zip archive containing note and attachments.

    After archiving, cleans up the original files.

    Args:
        base_path: Base path for archive (without extension).
        note_file: Path to the exported note file.
        attachments_dir: Path to attachments directory, or None if no attachments.

    Returns:
        Path to created .7z archive.
    """
    archive_path = base_path.with_suffix(".7z")

    with py7zr.SevenZipFile(archive_path, "w") as archive:
        # Add note file at root
        archive.write(note_file, note_file.name)

        # Add attachments directory if present
        if attachments_dir and attachments_dir.exists():
            for file in attachments_dir.rglob("*"):
                if file.is_file():
                    arcname = f"{attachments_dir.name}/{file.relative_to(attachments_dir)}"
                    archive.write(file, arcname)

    # Clean up temporary files after archiving
    note_file.unlink()
    if attachments_dir and attachments_dir.exists():
        shutil.rmtree(attachments_dir)

    return archive_path
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_attachments.py -k "create_archive" -v`
Expected: Both tests PASS

**Step 5: Commit**

```bash
git add src/noted/attachments.py tests/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(attachments): add 7zip archive creation

Creates .7z archive with note and attachments directory.
Cleans up source files after archiving.
EOF
)"
```

---

### Task 11: Add display_warning Function

**Files:**
- Modify: `src/noted/display.py`
- Test: `tests/test_display.py`

**Step 1: Write the failing test**

Add to `tests/test_display.py`:

```python
from io import StringIO
from unittest.mock import patch

from noted.display import display_warning


def test_display_warning() -> None:
    """Test warning message display."""
    with patch("noted.display.console") as mock_console:
        display_warning("Skipped 2 attachments")
        mock_console.print.assert_called_once()
        call_arg = mock_console.print.call_args[0][0]
        assert "Warning" in call_arg or "warning" in call_arg.lower()
        assert "Skipped 2 attachments" in call_arg
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_display.py::test_display_warning -v`
Expected: FAIL with "cannot import name 'display_warning'"

**Step 3: Write minimal implementation**

Add to `src/noted/display.py` after `display_success`:

```python
def display_warning(message: str) -> None:
    """Display warning message.

    Args:
        message: Warning message to display.
    """
    console.print(f"[bold yellow]Warning:[/bold yellow] {message}")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_display.py::test_display_warning -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/noted/display.py tests/test_display.py
git commit -m "$(cat <<'EOF'
feat(display): add display_warning function

Shows yellow warning messages for non-critical issues.
EOF
)"
```

---

### Task 12: Update CLI with --attachments and --zip Options

**Files:**
- Modify: `src/noted/cli.py:78-193`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock


def test_view_zip_without_attachments() -> None:
    """Test that --zip without --attachments shows error."""
    result = runner.invoke(app, ["view", "42", "--zip"])
    assert result.exit_code == 1
    assert "requires" in result.output.lower() or "attachments" in result.output.lower()


def test_view_attachments_flag_exports(tmp_path: Path) -> None:
    """Test --attachments flag triggers export."""
    mock_note = Note(
        id=42,
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )

    # Build valid protobuf with no attachments
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with (
        patch("noted.cli.db.get_connection"),
        patch("noted.cli.db.get_note_by_id", return_value=mock_note),
        patch("noted.cli.db.get_note_content", return_value=compressed),
        patch("noted.cli.db.get_attachment_names", return_value={}),
        patch("noted.cli.Path.cwd", return_value=tmp_path),
    ):
        result = runner.invoke(app, ["view", "42", "--attachments"])

    assert result.exit_code == 0
    # Should create note file in tmp_path
    note_files = list(tmp_path.glob("*.md")) + list(tmp_path.glob("*.txt"))
    assert len(note_files) >= 1 or "Exported" in result.output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_view_zip_without_attachments -v`
Expected: FAIL (--zip option doesn't exist yet)

**Step 3: Write the implementation**

Replace the `view` command in `src/noted/cli.py`:

```python
@app.command()
def view(
    note_id: int = typer.Argument(..., help="Note ID to view (from list command)."),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        "-md",
        help="Output as raw markdown text.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON.",
    ),
    json_styled: bool = typer.Option(
        False,
        "--json-styled",
        help="Include styling metadata in JSON output.",
    ),
    html: bool = typer.Option(
        False,
        "--html",
        help="Output as standalone HTML5 document.",
    ),
    export: Path | None = typer.Option(
        None,
        "--export",
        "-o",
        help="Export to file (extension auto-selected based on format).",
    ),
    attachments_flag: bool = typer.Option(
        False,
        "--attachments",
        "-a",
        help="Export attachments alongside note file.",
    ),
    zip_archive: bool = typer.Option(
        False,
        "--zip",
        "-z",
        help="Compress output as 7zip archive (requires --attachments).",
    ),
) -> None:
    """View the full content of a note."""
    # Validate options
    if zip_archive and not attachments_flag:
        display.display_error("--zip requires --attachments")
        raise typer.Exit(code=1)

    try:
        conn = db.get_connection()

        # Get note metadata
        note = db.get_note_by_id(conn, note_id)
        if note is None:
            display.display_error(f"Note with ID {note_id} not found.")
            conn.close()
            raise typer.Exit(code=1)

        # Get note content
        raw_data = db.get_note_content(conn, note_id)

        if raw_data is None:
            conn.close()
            display.display_error("Note has no content.")
            raise typer.Exit(code=1)

        # Check if locked
        if protobuf.is_note_locked(raw_data):
            conn.close()
            display.display_error("Note is locked and cannot be read.")
            raise typer.Exit(code=1)

        # Get attachment names for display
        attachment_names = db.get_attachment_names(conn, note_id)

        # Parse content with formatting
        content = protobuf.parse_note_data(
            raw_data,
            attachment_names,
            include_formatting=True,
        )

        # Parse table attachments
        if content.attachments:
            for attachment in content.attachments:
                if attachment.type_uti == "com.apple.notes.table":
                    result = db.get_table_data(conn, attachment.identifier)
                    if result:
                        table_data, summary = result
                        attachment.table = tables.parse_table_data(table_data, summary)

        # Determine output format and get content
        if json_output or json_styled:
            output = display.get_note_json(note, content, include_styling=json_styled)
            ext = ".json"
        elif html:
            output = display.get_note_html(note, content)
            ext = ".html"
        elif markdown:
            output = display.get_note_markdown(note, content)
            ext = ".md"
        else:
            output = None  # Rich text display handled separately
            ext = ".txt"

        # Handle attachments export
        if attachments_flag:
            from noted import attachments as att_module

            # Determine base path
            if export:
                base_path = export.with_suffix("")
            else:
                base_path = Path.cwd() / att_module.sanitize_filename(note.title)

            # Ensure we have markdown output for export (default if none specified)
            if output is None:
                output = display.get_note_markdown(note, content)
                ext = ".md"

            # Write note file
            note_path = base_path.with_suffix(ext)
            note_path.write_text(output, encoding="utf-8")

            # Export attachments
            export_result = att_module.AttachmentExportResult(
                exported=[], skipped=[], manifest_path=None, attachments_dir=None
            )
            if content.attachments:
                export_result = att_module.export_attachments(
                    conn=conn,
                    attachments=content.attachments,
                    output_dir=base_path.parent,
                    base_name=base_path.name,
                    note_id=note_id,
                    note_title=note.title,
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

            # Report attachment results
            if export_result.exported:
                display.display_success(f"Exported {len(export_result.exported)} attachments")
            if export_result.skipped:
                # Summarize skipped by type
                from collections import Counter
                type_counts = Counter(
                    protobuf.UTI_TYPE_MAP.get(a.type_uti, "Unknown")
                    for a in export_result.skipped
                )
                summary = ", ".join(f"{v} {k}" for k, v in type_counts.items())
                display.display_warning(f"Skipped {len(export_result.skipped)} non-exportable: {summary}")

        else:
            conn.close()

            # Export to file or display
            if export:
                # Add extension if not provided
                export_path = export if export.suffix else export.with_suffix(ext)
                if output is not None:
                    export_path.write_text(output, encoding="utf-8")
                else:
                    # For rich text, export as plain text
                    export_path.write_text(content.text or "", encoding="utf-8")
                display.display_success(f"Exported to {export_path}")
            elif output is not None:
                print(output)
            else:
                display.display_note_view(note, content)

    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Error viewing note")
        display.display_error(str(e))
        raise typer.Exit(code=1)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/cli.py && uv run ruff format src/noted/cli.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): add --attachments and --zip options to view command

--attachments exports note attachments to {name}_attachments/ directory.
--zip compresses output as 7zip archive.
Prints summary of exported/skipped attachments.
EOF
)"
```

---

### Task 13: Run Full Test Suite and Fix Issues

**Files:**
- All modified files

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 2: Run linting**

Run: `uv run ruff check src/ tests/`
Expected: No errors

**Step 3: Run type checking**

Run: `uv run pyrefly check`
Expected: No errors

**Step 4: Fix any issues found**

If any tests fail or linting errors occur, fix them before proceeding.

**Step 5: Commit fixes if any**

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix: resolve test and lint issues
EOF
)"
```

---

### Task 14: Manual Integration Test

**Step 1: Test basic attachment export**

Run: `uv run noted list` - Pick a note ID that has attachments

Run: `uv run noted view <note_id> --attachments`

Expected:
- Creates `{NoteTitle}.md` file in current directory
- Creates `{NoteTitle}_attachments/` directory with exported files
- Creates `manifest.json` in attachments directory
- Prints success messages

**Step 2: Test with --export path**

Run: `uv run noted view <note_id> -a -o /tmp/test_export`

Expected:
- Creates `/tmp/test_export.md`
- Creates `/tmp/test_export_attachments/`

**Step 3: Test --zip option**

Run: `uv run noted view <note_id> -a -z`

Expected:
- Creates `{NoteTitle}.7z` archive
- Archive contains note file and attachments directory
- No loose files left behind

**Step 4: Verify --zip without --attachments fails**

Run: `uv run noted view <note_id> --zip`

Expected: Error message about --zip requiring --attachments

---

### Task 15: Final Commit and Summary

**Step 1: Verify all changes committed**

Run: `git status`
Expected: Clean working tree

**Step 2: View commit log**

Run: `git log --oneline -15`

Expected: Series of focused commits for the feature

**Step 3: Create summary**

The attachment export feature is complete with:
- `--attachments` / `-a` flag to export attachments
- `--zip` / `-z` flag for 7zip compression
- Automatic directory naming from note title
- manifest.json with all attachment metadata
- Skip handling for non-exportable types (tables, links, etc.)
- Filename conflict resolution with UUID suffix
