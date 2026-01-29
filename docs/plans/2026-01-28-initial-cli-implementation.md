# Initial CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first working version of the `noted` CLI with `list`, `count`, and `refresh` commands.

**Architecture:** Layered design with CLI → DB → Models → Display. Database layer handles caching automatically. All commands operate on a cached copy of the Apple Notes SQLite database.

**Tech Stack:** Python 3.14+, Typer, Rich, Loguru, pytest, uv

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `src/noted/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "noted"
version = "0.1.0"
description = "CLI tool for working with Apple Notes database"
requires-python = ">=3.14"
dependencies = [
    "typer>=0.15",
    "rich>=13",
    "loguru>=0.7",
]

[project.scripts]
noted = "noted.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/noted"]

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyrefly]
project_includes = ["src"]
```

**Step 2: Create package init**

```python
"""Apple Notes CLI utility."""

__version__ = "0.1.0"
```

**Step 3: Create directories and install dependencies**

Run:
```bash
mkdir -p src/noted tests
uv sync
```

Expected: Dependencies installed, lock file created

**Step 4: Verify installation**

Run: `uv run python -c "import noted; print(noted.__version__)"`

Expected: `0.1.0`

**Step 5: Commit**

```bash
git add pyproject.toml src/noted/__init__.py uv.lock
git commit -m "chore: initial project setup with uv"
```

---

## Task 2: Models

**Files:**
- Create: `src/noted/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
"""Tests for noted.models."""

from datetime import datetime

from noted.models import Note, NoteSummary


def test_note_creation() -> None:
    """Test Note dataclass creation."""
    note = Note(
        id=1,
        title="Test Note",
        folder="Personal",
        created=datetime(2025, 1, 15, 10, 30),
        modified=datetime(2025, 1, 28, 14, 45),
    )
    assert note.id == 1
    assert note.title == "Test Note"
    assert note.folder == "Personal"
    assert note.created == datetime(2025, 1, 15, 10, 30)
    assert note.modified == datetime(2025, 1, 28, 14, 45)


def test_note_with_none_folder() -> None:
    """Test Note with no folder."""
    note = Note(
        id=2,
        title="Orphan Note",
        folder=None,
        created=datetime(2025, 1, 1),
        modified=datetime(2025, 1, 1),
    )
    assert note.folder is None


def test_note_summary_creation() -> None:
    """Test NoteSummary dataclass creation."""
    summary = NoteSummary(
        total_count=42,
        folder_counts={"Personal": 20, "Work": 22},
    )
    assert summary.total_count == 42
    assert summary.folder_counts["Personal"] == 20
    assert summary.folder_counts["Work"] == 22


def test_note_summary_empty_folders() -> None:
    """Test NoteSummary with no folders."""
    summary = NoteSummary(total_count=0, folder_counts={})
    assert summary.total_count == 0
    assert summary.folder_counts == {}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'noted.models'`

**Step 3: Write minimal implementation**

```python
"""Data models for Apple Notes entities."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Note:
    """Represents an Apple Note.

    Attributes:
        id: The Z_PK primary key from the database.
        title: The note title (ZTITLE1 field).
        folder: The folder name, or None if not in a folder.
        created: When the note was created.
        modified: When the note was last modified.
    """

    id: int
    title: str
    folder: str | None
    created: datetime
    modified: datetime


@dataclass
class NoteSummary:
    """Aggregate statistics about the notes database.

    Attributes:
        total_count: Total number of notes.
        folder_counts: Mapping of folder name to note count.
    """

    total_count: int
    folder_counts: dict[str, int]
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`

Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/noted/models.py tests/test_models.py
git commit -m "feat: add Note and NoteSummary dataclasses"
```

---

## Task 3: Database Layer - Core Functions

**Files:**
- Create: `src/noted/db.py`
- Create: `tests/test_db.py`

**Step 1: Write the failing test for Apple timestamp conversion**

```python
"""Tests for noted.db."""

from datetime import datetime, timezone

from noted.db import apple_timestamp_to_datetime


def test_apple_timestamp_to_datetime() -> None:
    """Test conversion of Apple Core Data timestamp to datetime.

    Apple timestamps are seconds since 2001-01-01 00:00:00 UTC.
    """
    # 2025-01-15 10:30:00 UTC
    # Seconds from 2001-01-01 to 2025-01-15 10:30:00
    apple_ts = 758714200.0
    result = apple_timestamp_to_datetime(apple_ts)
    expected = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert result == expected


def test_apple_timestamp_none() -> None:
    """Test that None timestamp returns None."""
    result = apple_timestamp_to_datetime(None)
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_apple_timestamp_to_datetime -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'noted.db'`

**Step 3: Write minimal implementation**

```python
"""Database operations for Apple Notes.

Handles copying, caching, and querying the Notes SQLite database.
"""

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from noted.models import Note, NoteSummary

# Apple Notes database location
NOTES_DIR = Path.home() / "Library/Group Containers/group.com.apple.notes"

# Cache location for copied database
CACHE_DIR = Path.home() / ".cache/noted"

# Files that make up the SQLite database
DB_FILES = ["NoteStore.sqlite", "NoteStore.sqlite-shm", "NoteStore.sqlite-wal"]

# Apple Core Data epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def apple_timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert Apple Core Data timestamp to datetime.

    Apple timestamps are seconds since 2001-01-01 00:00:00 UTC.

    Args:
        timestamp: Apple timestamp in seconds, or None.

    Returns:
        datetime in UTC, or None if input was None.
    """
    if timestamp is None:
        return None
    return APPLE_EPOCH + __import__("datetime").timedelta(seconds=timestamp)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`

Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "feat: add Apple timestamp conversion"
```

---

## Task 4: Database Layer - Caching

**Files:**
- Modify: `src/noted/db.py`
- Modify: `tests/test_db.py`

**Step 1: Write the failing test for cache functions**

Add to `tests/test_db.py`:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch

from noted.db import (
    CACHE_DIR,
    _cache_is_fresh,
    _source_db_path,
    clear_cache,
    ensure_cached_db,
)


def test_source_db_path() -> None:
    """Test that source DB path is correct."""
    path = _source_db_path()
    assert path.name == "NoteStore.sqlite"
    assert "group.com.apple.notes" in str(path)


def test_cache_is_fresh_no_cache(tmp_path: Path) -> None:
    """Test cache freshness when no cache exists."""
    with patch("noted.db.CACHE_DIR", tmp_path):
        assert _cache_is_fresh() is False


def test_clear_cache(tmp_path: Path) -> None:
    """Test clearing the cache directory."""
    with patch("noted.db.CACHE_DIR", tmp_path):
        # Create fake cached files
        (tmp_path / "NoteStore.sqlite").write_text("fake")
        (tmp_path / "NoteStore.sqlite-wal").write_text("fake")

        clear_cache()

        assert not (tmp_path / "NoteStore.sqlite").exists()
        assert not (tmp_path / "NoteStore.sqlite-wal").exists()


def test_clear_cache_no_dir(tmp_path: Path) -> None:
    """Test clearing cache when directory doesn't exist."""
    nonexistent = tmp_path / "nonexistent"
    with patch("noted.db.CACHE_DIR", nonexistent):
        # Should not raise
        clear_cache()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_source_db_path -v`

Expected: FAIL with `ImportError: cannot import name '_source_db_path'`

**Step 3: Write implementation for caching functions**

Add to `src/noted/db.py`:

```python
def _source_db_path() -> Path:
    """Get path to the source Notes database.

    Returns:
        Path to NoteStore.sqlite in Apple Notes directory.
    """
    return NOTES_DIR / "NoteStore.sqlite"


def _source_mtime() -> float:
    """Get modification time of source database.

    Returns:
        Modification time as Unix timestamp.

    Raises:
        FileNotFoundError: If source database doesn't exist.
    """
    return _source_db_path().stat().st_mtime


def _cache_is_fresh() -> bool:
    """Check if cached copy exists and is newer than source.

    Returns:
        True if cache exists and is at least as new as source.
    """
    cached = CACHE_DIR / "NoteStore.sqlite"
    if not cached.exists():
        return False
    try:
        return cached.stat().st_mtime >= _source_mtime()
    except FileNotFoundError:
        return False


def ensure_cached_db() -> Path:
    """Ensure database is cached, copying if stale or missing.

    Copies all SQLite files (db, wal, shm) to cache directory.
    Only copies if source is newer than cache.

    Returns:
        Path to cached NoteStore.sqlite.

    Raises:
        FileNotFoundError: If source database doesn't exist.
    """
    if not _cache_is_fresh():
        logger.info("Cache stale or missing, copying database...")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for filename in DB_FILES:
            src = NOTES_DIR / filename
            if src.exists():
                shutil.copy2(src, CACHE_DIR / filename)
                logger.debug(f"Copied {filename}")
        logger.info(f"Database cached to {CACHE_DIR}")
    else:
        logger.debug("Using cached database")
    return CACHE_DIR / "NoteStore.sqlite"


def clear_cache() -> None:
    """Delete cached database files to force refresh on next access."""
    if not CACHE_DIR.exists():
        return
    for filename in DB_FILES:
        cached = CACHE_DIR / filename
        if cached.exists():
            cached.unlink()
            logger.debug(f"Deleted {filename}")
    logger.info("Cache cleared")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "feat: add database caching functions"
```

---

## Task 5: Database Layer - Connection and Queries

**Files:**
- Modify: `src/noted/db.py`
- Modify: `tests/test_db.py`

**Step 1: Write the failing test for connection**

Add to `tests/test_db.py`:

```python
def test_get_connection(tmp_path: Path) -> None:
    """Test getting a read-only database connection."""
    # Create a minimal SQLite database for testing
    test_db = tmp_path / "NoteStore.sqlite"
    conn = sqlite3.connect(test_db)
    conn.execute("CREATE TABLE test (id INTEGER)")
    conn.close()

    with patch("noted.db.ensure_cached_db", return_value=test_db):
        from noted.db import get_connection
        conn = get_connection()
        assert conn is not None
        # Verify it's read-only by trying to write
        try:
            conn.execute("INSERT INTO test VALUES (1)")
            conn.commit()
            assert False, "Should have raised error for read-only"
        except sqlite3.OperationalError as e:
            assert "readonly" in str(e).lower()
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_connection -v`

Expected: FAIL with `ImportError: cannot import name 'get_connection'`

**Step 3: Write implementation for connection and queries**

Add to `src/noted/db.py`:

```python
def get_connection() -> sqlite3.Connection:
    """Get a read-only connection to the cached database.

    Ensures database is cached first, then opens in read-only mode.

    Returns:
        SQLite connection in read-only mode.
    """
    db_path = ensure_cached_db()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_notes(
    conn: sqlite3.Connection,
    folder: str | None = None,
    limit: int | None = None,
) -> list[Note]:
    """Query notes from the database.

    Args:
        conn: Database connection.
        folder: Filter by folder name, or None for all.
        limit: Maximum number of notes to return, or None for all.

    Returns:
        List of Note objects sorted by modification date (newest first).
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
        WHERE n.ZTITLE1 IS NOT NULL
          AND n.ZMARKEDFORDELETION != 1
    """
    params: list[str | int] = []

    if folder is not None:
        query += " AND f.ZTITLE2 = ?"
        params.append(folder)

    query += " ORDER BY n.ZMODIFICATIONDATE DESC"

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    cursor = conn.execute(query, params)
    notes = []
    for row in cursor:
        notes.append(
            Note(
                id=row["id"],
                title=row["title"] or "(Untitled)",
                folder=row["folder"],
                created=apple_timestamp_to_datetime(row["created"]),
                modified=apple_timestamp_to_datetime(row["modified"]),
            )
        )
    return notes


def count_notes(conn: sqlite3.Connection) -> int:
    """Count total notes in database.

    Args:
        conn: Database connection.

    Returns:
        Total number of notes.
    """
    query = """
        SELECT COUNT(*)
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE1 IS NOT NULL
          AND ZMARKEDFORDELETION != 1
    """
    cursor = conn.execute(query)
    return cursor.fetchone()[0]


def get_summary(conn: sqlite3.Connection, by_folder: bool = False) -> NoteSummary:
    """Get aggregate statistics about notes.

    Args:
        conn: Database connection.
        by_folder: Whether to include per-folder counts.

    Returns:
        NoteSummary with total count and optional folder breakdown.
    """
    total = count_notes(conn)
    folder_counts: dict[str, int] = {}

    if by_folder:
        query = """
            SELECT
                COALESCE(f.ZTITLE2, '(No Folder)') as folder,
                COUNT(*) as count
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
            WHERE n.ZTITLE1 IS NOT NULL
              AND n.ZMARKEDFORDELETION != 1
            GROUP BY f.ZTITLE2
            ORDER BY count DESC
        """
        cursor = conn.execute(query)
        for row in cursor:
            folder_counts[row["folder"]] = row["count"]

    return NoteSummary(total_count=total, folder_counts=folder_counts)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/noted/db.py tests/test_db.py
git commit -m "feat: add database connection and query functions"
```

---

## Task 6: Display Layer

**Files:**
- Create: `src/noted/display.py`
- Create: `tests/test_display.py`

**Step 1: Write the failing test**

```python
"""Tests for noted.display."""

from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

from noted.display import display_count, display_notes_table
from noted.models import Note, NoteSummary


def test_display_notes_table_renders() -> None:
    """Test that notes table renders without error."""
    notes = [
        Note(
            id=1,
            title="Test Note",
            folder="Personal",
            created=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
            modified=datetime(2025, 1, 28, 14, 45, tzinfo=timezone.utc),
        ),
    ]
    # Should not raise
    display_notes_table(notes)


def test_display_notes_table_empty() -> None:
    """Test displaying empty notes list."""
    # Should not raise
    display_notes_table([])


def test_display_count_total() -> None:
    """Test displaying total count."""
    summary = NoteSummary(total_count=42, folder_counts={})
    # Should not raise
    display_count(summary)


def test_display_count_by_folder() -> None:
    """Test displaying counts by folder."""
    summary = NoteSummary(
        total_count=42,
        folder_counts={"Personal": 20, "Work": 22},
    )
    # Should not raise
    display_count(summary)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_display.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'noted.display'`

**Step 3: Write implementation**

```python
"""Terminal display formatting using Rich."""

from rich.console import Console
from rich.table import Table

from noted.models import Note, NoteSummary

console = Console()


def display_notes_table(notes: list[Note]) -> None:
    """Render notes as a Rich table.

    Args:
        notes: List of notes to display.
    """
    if not notes:
        console.print("[yellow]No notes found.[/yellow]")
        return

    table = Table(title="Notes", show_lines=False)
    table.add_column("ID", style="dim", width=6)
    table.add_column("Title", style="bold")
    table.add_column("Folder", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Modified", style="green")

    for note in notes:
        created_str = note.created.strftime("%Y-%m-%d %H:%M") if note.created else "-"
        modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"
        table.add_row(
            str(note.id),
            note.title,
            note.folder or "(No Folder)",
            created_str,
            modified_str,
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(notes)} notes[/dim]")


def display_count(summary: NoteSummary) -> None:
    """Display note counts.

    Args:
        summary: NoteSummary with counts.
    """
    console.print(f"[bold]Total notes:[/bold] {summary.total_count}")

    if summary.folder_counts:
        console.print("\n[bold]By folder:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Folder")
        table.add_column("Count", justify="right")

        for folder, count in summary.folder_counts.items():
            table.add_row(folder, str(count))

        console.print(table)


def display_error(message: str) -> None:
    """Display error message.

    Args:
        message: Error message to display.
    """
    console.print(f"[bold red]Error:[/bold red] {message}")


def display_success(message: str) -> None:
    """Display success message.

    Args:
        message: Success message to display.
    """
    console.print(f"[bold green]✓[/bold green] {message}")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_display.py -v`

Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/noted/display.py tests/test_display.py
git commit -m "feat: add Rich display formatting"
```

---

## Task 7: CLI Commands

**Files:**
- Create: `src/noted/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write the failing test**

```python
"""Tests for noted.cli."""

from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from noted.cli import app
from noted.models import Note, NoteSummary

runner = CliRunner()


def test_list_command() -> None:
    """Test the list command."""
    mock_notes = [
        Note(
            id=1,
            title="Test Note",
            folder="Personal",
            created=datetime(2025, 1, 15, tzinfo=timezone.utc),
            modified=datetime(2025, 1, 28, tzinfo=timezone.utc),
        ),
    ]

    with patch("noted.cli.db.get_connection") as mock_conn, \
         patch("noted.cli.db.list_notes", return_value=mock_notes):
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "Test Note" in result.output


def test_count_command() -> None:
    """Test the count command."""
    mock_summary = NoteSummary(total_count=42, folder_counts={})

    with patch("noted.cli.db.get_connection"), \
         patch("noted.cli.db.get_summary", return_value=mock_summary):
        result = runner.invoke(app, ["count"])
        assert result.exit_code == 0
        assert "42" in result.output


def test_count_by_folder() -> None:
    """Test the count --by-folder command."""
    mock_summary = NoteSummary(
        total_count=42,
        folder_counts={"Personal": 20, "Work": 22},
    )

    with patch("noted.cli.db.get_connection"), \
         patch("noted.cli.db.get_summary", return_value=mock_summary):
        result = runner.invoke(app, ["count", "--by-folder"])
        assert result.exit_code == 0
        assert "Personal" in result.output
        assert "Work" in result.output


def test_refresh_command() -> None:
    """Test the refresh command."""
    with patch("noted.cli.db.clear_cache") as mock_clear:
        result = runner.invoke(app, ["refresh"])
        assert result.exit_code == 0
        mock_clear.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'noted.cli'`

**Step 3: Write implementation**

```python
"""CLI commands for noted using Typer."""

import typer
from loguru import logger

from noted import db
from noted import display

app = typer.Typer(
    name="noted",
    help="CLI tool for working with Apple Notes database.",
    no_args_is_help=True,
)


@app.command()
def list(
    folder: str | None = typer.Option(
        None,
        "--folder",
        "-f",
        help="Filter by folder name.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        help="Limit number of results.",
    ),
) -> None:
    """List all notes."""
    try:
        conn = db.get_connection()
        notes = db.list_notes(conn, folder=folder, limit=limit)
        display.display_notes_table(notes)
        conn.close()
    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.exception("Error listing notes")
        display.display_error(str(e))
        raise typer.Exit(code=1)


@app.command()
def count(
    by_folder: bool = typer.Option(
        False,
        "--by-folder",
        "-f",
        help="Show counts per folder.",
    ),
) -> None:
    """Count total notes."""
    try:
        conn = db.get_connection()
        summary = db.get_summary(conn, by_folder=by_folder)
        display.display_count(summary)
        conn.close()
    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.exception("Error counting notes")
        display.display_error(str(e))
        raise typer.Exit(code=1)


@app.command()
def refresh() -> None:
    """Force refresh the cached database copy."""
    db.clear_cache()
    display.display_success("Cache cleared. Next command will use fresh data.")


if __name__ == "__main__":
    app()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`

Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/noted/cli.py tests/test_cli.py
git commit -m "feat: add CLI commands for list, count, refresh"
```

---

## Task 8: Integration Test and Final Verification

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
"""Integration tests for noted CLI."""

from typer.testing import CliRunner

from noted.cli import app

runner = CliRunner()


def test_help() -> None:
    """Test that help is displayed."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "noted" in result.output.lower()
    assert "list" in result.output
    assert "count" in result.output
    assert "refresh" in result.output


def test_list_help() -> None:
    """Test list command help."""
    result = runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0
    assert "--folder" in result.output
    assert "--limit" in result.output


def test_count_help() -> None:
    """Test count command help."""
    result = runner.invoke(app, ["count", "--help"])
    assert result.exit_code == 0
    assert "--by-folder" in result.output
```

**Step 2: Run all tests**

Run: `uv run pytest -v`

Expected: All tests PASS

**Step 3: Run linting and type checking**

Run: `uv run ruff check src tests && uv run ruff format --check src tests`

Expected: No errors

**Step 4: Test the actual CLI**

Run: `uv run noted --help`

Expected: Help output showing list, count, refresh commands

Run: `uv run noted list --limit 5`

Expected: Table showing up to 5 notes from your Apple Notes

Run: `uv run noted count --by-folder`

Expected: Total count and breakdown by folder

**Step 5: Final commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for CLI"
```

---

## Summary

After completing all tasks, you will have:

- `pyproject.toml` - Project configuration with dependencies
- `src/noted/__init__.py` - Package init
- `src/noted/models.py` - Note and NoteSummary dataclasses
- `src/noted/db.py` - Database caching and queries
- `src/noted/display.py` - Rich terminal output
- `src/noted/cli.py` - Typer CLI commands
- `tests/` - Full test coverage

Commands available:
- `uv run noted list [--folder NAME] [--limit N]`
- `uv run noted count [--by-folder]`
- `uv run noted refresh`
