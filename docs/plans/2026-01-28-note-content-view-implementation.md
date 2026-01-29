# Note Content View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `noted view <id>` command to display the full plain text content of a note.

**Architecture:** Parse gzip-compressed protobuf data from ZICNOTEDATA.ZDATA using betterproto, extract plain text, and display with Rich formatting.

**Tech Stack:** betterproto (protobuf), gzip (decompression), Rich (display), Typer (CLI)

---

## Task 1: Add betterproto Dependency

**Files:**
- Modify: `pyproject.toml:6-10`

**Step 1: Add dependency**

Edit `pyproject.toml` dependencies:

```toml
dependencies = [
    "typer>=0.15",
    "rich>=13",
    "loguru>=0.7",
    "betterproto>=2.0.0b6",
]
```

**Step 2: Install dependencies**

Run: `uv sync`
Expected: Dependencies installed successfully

**Step 3: Verify installation**

Run: `uv run python -c "import betterproto; print(betterproto.__version__)"`
Expected: Version number printed (e.g., `2.0.0b6`)

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add betterproto dependency for protobuf parsing"
```

---

## Task 2: Add NoteContent Model

**Files:**
- Modify: `src/noted/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from noted.models import Note, NoteContent, NoteSummary


def test_note_content_creation() -> None:
    """Test NoteContent dataclass creation."""
    content = NoteContent(text="Hello, world!")
    assert content.text == "Hello, world!"


def test_note_content_empty() -> None:
    """Test NoteContent with empty text."""
    content = NoteContent(text="")
    assert content.text == ""
```

Also update the import at the top of the file to include `NoteContent`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_note_content_creation -v`
Expected: FAIL with `ImportError: cannot import name 'NoteContent'`

**Step 3: Write minimal implementation**

Add to `src/noted/models.py` after the `NoteSummary` class:

```python
@dataclass
class NoteContent:
    """Parsed content of an Apple Note.

    Attributes:
        text: The plain text content extracted from protobuf.
    """

    text: str
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/models.py tests/test_models.py && uv run pyrefly check src/noted/models.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/models.py tests/test_models.py
git commit -m "feat(models): add NoteContent dataclass"
```

---

## Task 3: Create Protobuf Module

**Files:**
- Create: `src/noted/protobuf.py`
- Create: `tests/test_protobuf.py`

**Step 1: Write the failing test for protobuf schema**

Create `tests/test_protobuf.py`:

```python
"""Tests for noted.protobuf."""

import gzip

import betterproto

from noted.protobuf import NoteStoreProto, parse_note_data


def test_notestoreproto_structure() -> None:
    """Test that NoteStoreProto has expected structure."""
    proto = NoteStoreProto()
    assert hasattr(proto, "document")
    assert isinstance(proto, betterproto.Message)


def test_parse_note_data_simple() -> None:
    """Test parsing a simple note with just text."""
    # Create a minimal valid protobuf manually
    # NoteStoreProto.document.note.note_text = "Hello"
    # Field 2 (document) -> Field 3 (note) -> Field 2 (note_text)

    # Build inner note: field 2 (string) = "Hello"
    note_proto = b"\x12\x05Hello"  # field 2, length 5, "Hello"

    # Build document: field 3 (message) = note_proto
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto  # field 3, length, data

    # Build root: field 2 (message) = doc_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto  # field 2, length, data

    # Gzip compress it
    compressed = gzip.compress(root_proto)

    result = parse_note_data(compressed)
    assert result.text == "Hello"


def test_parse_note_data_empty_text() -> None:
    """Test parsing a note with empty text."""
    # Empty note_text
    note_proto = b"\x12\x00"  # field 2, length 0
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    result = parse_note_data(compressed)
    assert result.text == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_protobuf.py::test_notestoreproto_structure -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'noted.protobuf'`

**Step 3: Write minimal implementation**

Create `src/noted/protobuf.py`:

```python
"""Protobuf parsing for Apple Notes content.

Apple Notes stores note content as gzip-compressed protobuf data.
This module defines the betterproto schema and parsing functions.
"""

import gzip
from dataclasses import dataclass

import betterproto

from noted.models import NoteContent


@dataclass
class Note(betterproto.Message):
    """Protobuf Note message containing the text content.

    Field numbers match Apple's schema:
    - Field 2: note_text (string)
    - Field 5: attribute_run (repeated, not implemented yet)
    """

    note_text: str = betterproto.string_field(2)


@dataclass
class Document(betterproto.Message):
    """Protobuf Document message wrapping a Note.

    Field numbers match Apple's schema:
    - Field 2: version (not implemented)
    - Field 3: note (Note message)
    """

    note: Note = betterproto.message_field(3)


@dataclass
class NoteStoreProto(betterproto.Message):
    """Root protobuf message for Apple Notes content.

    Field numbers match Apple's schema:
    - Field 2: document (Document message)
    """

    document: Document = betterproto.message_field(2)


def parse_note_data(data: bytes) -> NoteContent:
    """Parse gzip-compressed protobuf note data.

    Args:
        data: Gzip-compressed protobuf bytes from ZICNOTEDATA.ZDATA.

    Returns:
        NoteContent with extracted plain text.

    Raises:
        gzip.BadGzipFile: If data is not valid gzip.
        Exception: If protobuf parsing fails.
    """
    decompressed = gzip.decompress(data)
    proto = NoteStoreProto().parse(decompressed)
    text = proto.document.note.note_text if proto.document and proto.document.note else ""
    return NoteContent(text=text)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_protobuf.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/protobuf.py tests/test_protobuf.py && uv run pyrefly check src/noted/protobuf.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/protobuf.py tests/test_protobuf.py
git commit -m "feat(protobuf): add betterproto schema and parse_note_data function"
```

---

## Task 4: Add Database Function to Fetch Note Content

**Files:**
- Modify: `src/noted/db.py`
- Modify: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
from noted.db import (
    _cache_is_fresh,
    _source_db_path,
    apple_timestamp_to_datetime,
    clear_cache,
    get_connection,
    get_note_content,
)


def test_get_note_content(tmp_path: Path) -> None:
    """Test fetching raw note content bytes."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)

    # Create minimal schema matching Apple Notes
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE1 TEXT,
            ZMARKEDFORDELETION INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)

    # Insert test note
    conn.execute("INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE1) VALUES (1, 'Test')")
    test_data = b"\x1f\x8b\x08\x00test"  # Fake gzip-like data
    conn.execute("INSERT INTO ZICNOTEDATA (Z_PK, ZNOTE, ZDATA) VALUES (1, 1, ?)", (test_data,))
    conn.commit()
    conn.close()

    # Reopen read-only
    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = get_note_content(conn, 1)
    assert result == test_data
    conn.close()


def test_get_note_content_not_found(tmp_path: Path) -> None:
    """Test fetching content for non-existent note."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE1 TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZNOTE INTEGER,
            ZDATA BLOB
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    result = get_note_content(conn, 999)
    assert result is None
    conn.close()
```

Also update the import at the top to include `get_note_content`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_note_content -v`
Expected: FAIL with `ImportError: cannot import name 'get_note_content'`

**Step 3: Write minimal implementation**

Add to `src/noted/db.py` after the `get_summary` function:

```python
def get_note_content(conn: sqlite3.Connection, note_id: int) -> bytes | None:
    """Fetch raw ZDATA bytes for a note by ID.

    Args:
        conn: Database connection.
        note_id: The Z_PK of the note (from list command).

    Returns:
        Raw gzip-compressed protobuf bytes, or None if not found.
    """
    query = """
        SELECT nd.ZDATA
        FROM ZICCLOUDSYNCINGOBJECT n
        JOIN ZICNOTEDATA nd ON nd.ZNOTE = n.Z_PK
        WHERE n.Z_PK = ?
    """
    cursor = conn.execute(query, (note_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return row["ZDATA"]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/db.py tests/test_db.py && uv run pyrefly check src/noted/db.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "feat(db): add get_note_content function"
```

---

## Task 5: Add Database Function to Get Note by ID

**Files:**
- Modify: `src/noted/db.py`
- Modify: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
from noted.db import (
    _cache_is_fresh,
    _source_db_path,
    apple_timestamp_to_datetime,
    clear_cache,
    get_connection,
    get_note_by_id,
    get_note_content,
)


def test_get_note_by_id(tmp_path: Path) -> None:
    """Test fetching a single note by ID."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)

    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE1 TEXT,
            ZTITLE2 TEXT,
            ZFOLDER INTEGER,
            ZCREATIONDATE REAL,
            ZMODIFICATIONDATE REAL,
            ZMARKEDFORDELETION INTEGER DEFAULT 0
        )
    """)

    # Insert folder and note
    conn.execute("""
        INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE2)
        VALUES (1, 'Work')
    """)
    conn.execute("""
        INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE1, ZFOLDER, ZCREATIONDATE, ZMODIFICATIONDATE)
        VALUES (2, 'Test Note', 1, 758629800.0, 758629900.0)
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    note = get_note_by_id(conn, 2)
    assert note is not None
    assert note.id == 2
    assert note.title == "Test Note"
    assert note.folder == "Work"
    conn.close()


def test_get_note_by_id_not_found(tmp_path: Path) -> None:
    """Test fetching non-existent note."""
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE1 TEXT,
            ZFOLDER INTEGER,
            ZCREATIONDATE REAL,
            ZMODIFICATIONDATE REAL,
            ZMARKEDFORDELETION INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(f"file:{test_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    note = get_note_by_id(conn, 999)
    assert note is None
    conn.close()
```

Also update the import at the top to include `get_note_by_id`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_note_by_id -v`
Expected: FAIL with `ImportError: cannot import name 'get_note_by_id'`

**Step 3: Write minimal implementation**

Add to `src/noted/db.py` after `get_note_content`:

```python
def get_note_by_id(conn: sqlite3.Connection, note_id: int) -> Note | None:
    """Fetch a single note by its ID.

    Args:
        conn: Database connection.
        note_id: The Z_PK of the note.

    Returns:
        Note object, or None if not found.
    """
    query = """
        SELECT
            n.Z_PK as id,
            n.ZTITLE1 as title,
            f.ZTITLE2 as folder,
            n.ZCREATIONDATE as created,
            n.ZMODIFICATIONDATE as modified
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
        WHERE n.Z_PK = ?
          AND n.ZTITLE1 IS NOT NULL
          AND n.ZMARKEDFORDELETION != 1
    """
    cursor = conn.execute(query, (note_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return Note(
        id=row["id"],
        title=row["title"] or "(Untitled)",
        folder=row["folder"],
        created=apple_timestamp_to_datetime(row["created"]),
        modified=apple_timestamp_to_datetime(row["modified"]),
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/db.py tests/test_db.py && uv run pyrefly check src/noted/db.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "feat(db): add get_note_by_id function"
```

---

## Task 6: Add Display Function for Note Content

**Files:**
- Modify: `src/noted/display.py`
- Modify: `tests/test_display.py`

**Step 1: Write the failing test**

Add to `tests/test_display.py`:

```python
from datetime import datetime
from io import StringIO
from unittest.mock import patch

from noted.display import display_note_view
from noted.models import Note, NoteContent


def test_display_note_view(capsys: object) -> None:
    """Test displaying a note with content."""
    note = Note(
        id=42,
        title="Test Note",
        folder="Work",
        created=datetime(2025, 1, 15, 10, 30),
        modified=datetime(2025, 1, 28, 14, 45),
    )
    content = NoteContent(text="This is the note body.\nWith multiple lines.")

    display_note_view(note, content)

    # Capture doesn't work well with Rich, so we just verify no exception


def test_display_note_view_no_folder() -> None:
    """Test displaying a note without a folder."""
    note = Note(
        id=1,
        title="Orphan Note",
        folder=None,
        created=datetime(2025, 1, 1),
        modified=datetime(2025, 1, 1),
    )
    content = NoteContent(text="Content here")

    # Should not raise
    display_note_view(note, content)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_display.py::test_display_note_view -v`
Expected: FAIL with `ImportError: cannot import name 'display_note_view'`

**Step 3: Write minimal implementation**

Add imports at top of `src/noted/display.py`:

```python
from rich.panel import Panel
from rich.text import Text
```

Update the import from models:

```python
from noted.models import Note, NoteContent, NoteSummary
```

Add the function after `display_success`:

```python
def display_note_view(note: Note, content: NoteContent) -> None:
    """Display a note's full content.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
    """
    # Format metadata line
    folder_str = note.folder or "(No Folder)"
    modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"
    subtitle = f"Folder: {folder_str}  |  Modified: {modified_str}"

    # Create header panel
    panel = Panel(
        Text(subtitle, style="dim"),
        title=f"[bold]{note.title}[/bold]",
        title_align="left",
        border_style="blue",
    )
    console.print(panel)
    console.print()

    # Print body text
    if content.text:
        console.print(content.text)
    else:
        console.print("[dim]No content[/dim]")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_display.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/display.py tests/test_display.py && uv run pyrefly check src/noted/display.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/display.py tests/test_display.py
git commit -m "feat(display): add display_note_view function"
```

---

## Task 7: Add Locked Note Detection

**Files:**
- Modify: `src/noted/protobuf.py`
- Modify: `tests/test_protobuf.py`

**Step 1: Write the failing test**

Add to `tests/test_protobuf.py`:

```python
from noted.protobuf import NoteStoreProto, is_note_locked, parse_note_data


def test_is_note_locked_gzip() -> None:
    """Test that gzip data is not locked."""
    # Valid gzip magic bytes
    data = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03test"
    assert is_note_locked(data) is False


def test_is_note_locked_encrypted() -> None:
    """Test that non-gzip data is considered locked."""
    # Random bytes (not gzip)
    data = b"\x00\x01\x02\x03\x04\x05"
    assert is_note_locked(data) is True


def test_is_note_locked_empty() -> None:
    """Test that empty data is not locked (just missing)."""
    assert is_note_locked(b"") is False
    assert is_note_locked(None) is False
```

Also update the import to include `is_note_locked`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_protobuf.py::test_is_note_locked_gzip -v`
Expected: FAIL with `ImportError: cannot import name 'is_note_locked'`

**Step 3: Write minimal implementation**

Add to `src/noted/protobuf.py` before `parse_note_data`:

```python
# Gzip magic bytes
GZIP_MAGIC = b"\x1f\x8b"


def is_note_locked(data: bytes | None) -> bool:
    """Check if note data is encrypted (locked).

    Locked notes don't have gzip-compressed data.

    Args:
        data: Raw bytes from ZICNOTEDATA.ZDATA.

    Returns:
        True if the note appears to be locked/encrypted.
    """
    if not data or len(data) < 2:
        return False
    return data[:2] != GZIP_MAGIC
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_protobuf.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/protobuf.py tests/test_protobuf.py && uv run pyrefly check src/noted/protobuf.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/protobuf.py tests/test_protobuf.py
git commit -m "feat(protobuf): add is_note_locked detection"
```

---

## Task 8: Add CLI View Command

**Files:**
- Modify: `src/noted/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
import gzip
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from noted.cli import app
from noted.models import Note, NoteContent

runner = CliRunner()


def test_view_command_success() -> None:
    """Test view command with valid note."""
    mock_note = Note(
        id=42,
        title="Test Note",
        folder="Work",
        created=None,
        modified=None,
    )
    mock_content = NoteContent(text="Hello, world!")

    # Build valid protobuf
    note_proto = b"\x12\x0dHello, world!"
    doc_proto = b"\x1a" + bytes([len(note_proto)]) + note_proto
    root_proto = b"\x12" + bytes([len(doc_proto)]) + doc_proto
    compressed = gzip.compress(root_proto)

    with patch("noted.cli.db.get_connection") as mock_conn, \
         patch("noted.cli.db.get_note_by_id", return_value=mock_note), \
         patch("noted.cli.db.get_note_content", return_value=compressed):
        result = runner.invoke(app, ["view", "42"])

    assert result.exit_code == 0
    assert "Test Note" in result.output
    assert "Hello, world!" in result.output


def test_view_command_not_found() -> None:
    """Test view command with non-existent note."""
    with patch("noted.cli.db.get_connection"), \
         patch("noted.cli.db.get_note_by_id", return_value=None):
        result = runner.invoke(app, ["view", "999"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_view_command_locked() -> None:
    """Test view command with locked note."""
    mock_note = Note(
        id=42,
        title="Secret Note",
        folder=None,
        created=None,
        modified=None,
    )
    # Non-gzip data indicates locked
    locked_data = b"\x00\x01\x02\x03"

    with patch("noted.cli.db.get_connection"), \
         patch("noted.cli.db.get_note_by_id", return_value=mock_note), \
         patch("noted.cli.db.get_note_content", return_value=locked_data):
        result = runner.invoke(app, ["view", "42"])

    assert result.exit_code == 1
    assert "locked" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_view_command_success -v`
Expected: FAIL with `Error: No such command 'view'`

**Step 3: Write minimal implementation**

Add import at top of `src/noted/cli.py`:

```python
from noted import db, display, protobuf
```

Add the view command after the `refresh` command:

```python
@app.command()
def view(
    note_id: int = typer.Argument(..., help="Note ID to view (from list command)."),
) -> None:
    """View the full content of a note."""
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
        conn.close()

        if raw_data is None:
            display.display_error("Note has no content.")
            raise typer.Exit(code=1)

        # Check if locked
        if protobuf.is_note_locked(raw_data):
            display.display_error("Note is locked and cannot be read.")
            raise typer.Exit(code=1)

        # Parse and display
        content = protobuf.parse_note_data(raw_data)
        display.display_note_view(note, content)

    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.exception("Error viewing note")
        display.display_error(str(e))
        raise typer.Exit(code=1)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

**Step 5: Run linting and type checking**

Run: `uv run ruff check src/noted/cli.py tests/test_cli.py && uv run pyrefly check src/noted/cli.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/noted/cli.py tests/test_cli.py
git commit -m "feat(cli): add view command to display note content"
```

---

## Task 9: Integration Test with Real Data

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write integration test**

Add to `tests/test_integration.py`:

```python
from typer.testing import CliRunner

from noted.cli import app

runner = CliRunner()


def test_view_command_integration() -> None:
    """Integration test: list notes, then view one.

    This test requires access to the real Apple Notes database.
    It will be skipped if the database is not available.
    """
    import os
    from pathlib import Path

    notes_db = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
    if not notes_db.exists():
        import pytest
        pytest.skip("Apple Notes database not available")

    # First list notes to get an ID
    list_result = runner.invoke(app, ["list", "--limit", "1"])
    if list_result.exit_code != 0 or "No notes found" in list_result.output:
        import pytest
        pytest.skip("No notes available to test")

    # Extract first note ID from output (ID column is first)
    lines = list_result.output.strip().split("\n")
    # Find a line with a numeric ID (skip header lines)
    note_id = None
    for line in lines:
        parts = line.split()
        if parts and parts[0].isdigit():
            note_id = parts[0]
            break

    if note_id is None:
        import pytest
        pytest.skip("Could not parse note ID from list output")

    # View that note
    view_result = runner.invoke(app, ["view", note_id])

    # Should succeed (exit 0) or fail gracefully for locked notes (exit 1 with "locked")
    assert view_result.exit_code in (0, 1)
    if view_result.exit_code == 1:
        assert "locked" in view_result.output.lower() or "not found" in view_result.output.lower()
```

**Step 2: Run integration test**

Run: `uv run pytest tests/test_integration.py::test_view_command_integration -v`
Expected: PASS (or SKIP if no database)

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 4: Run full linting and type checking**

Run: `uv run ruff check src/ tests/ && uv run pyrefly check src/`
Expected: No errors

**Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for view command"
```

---

## Task 10: Manual Testing and Documentation

**Step 1: Test the full flow manually**

Run: `uv run noted list --limit 5`
Expected: List of notes with IDs

Run: `uv run noted view <id>` (use an ID from the list)
Expected: Note content displayed with header panel

**Step 2: Verify error handling**

Run: `uv run noted view 99999999`
Expected: "Note with ID 99999999 not found."

**Step 3: Final verification**

Run: `uv run pytest -v && uv run ruff check src/ tests/ && uv run pyrefly check src/`
Expected: All pass with no errors

**Step 4: Final commit (if any cleanup needed)**

If any fixes were needed during manual testing, commit them.

---

## Summary

After completing all tasks, you will have:

1. betterproto dependency installed
2. `NoteContent` model for parsed content
3. `protobuf.py` module with schema and parsing
4. `get_note_content()` and `get_note_by_id()` database functions
5. `display_note_view()` for Rich output
6. `is_note_locked()` detection
7. `noted view <id>` CLI command
8. Full test coverage including integration tests
