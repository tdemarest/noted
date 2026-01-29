# Initial CLI Design: List and Count Notes

**Date:** 2026-01-28
**Status:** Approved

## Overview

First iteration of the Apple Notes CLI utility. Provides commands to list and count notes from a cached copy of the database.

## Architecture

Layered architecture with four modules:

```
src/noted/
├── __init__.py      # Package metadata
├── cli.py           # Typer commands (thin layer)
├── db.py            # Database connection, caching, queries
├── models.py        # Data classes for Note, NoteSummary
└── display.py       # Rich formatting for terminal output
```

## Database Layer (`db.py`)

Handles SQLite operations with automatic caching to avoid repeated 100MB+ copies.

### Constants

```python
NOTES_DIR = Path.home() / "Library/Group Containers/group.com.apple.notes"
CACHE_DIR = Path.home() / ".cache/noted"
DB_FILES = ["NoteStore.sqlite", "NoteStore.sqlite-shm", "NoteStore.sqlite-wal"]
```

### Functions

- `ensure_cached_db() -> Path`: Copy DB files to cache if stale or missing, return cached path
- `get_connection() -> sqlite3.Connection`: Get read-only connection to cached database
- `list_notes(conn, folder, limit) -> list[Note]`: Query notes with optional filters
- `count_notes(conn) -> int`: Return total note count
- `get_summary(conn, by_folder) -> NoteSummary`: Return aggregate statistics
- `clear_cache() -> None`: Delete cached files to force refresh

### Caching Strategy

- Cache location: `~/.cache/noted/`
- Staleness check: compare mtime of source vs cached DB
- Copy uses `shutil.copy2()` to preserve timestamps
- All 3 files copied together (db + wal + shm) for consistency

## Models (`models.py`)

```python
@dataclass
class Note:
    id: int           # Z_PK from database
    title: str        # ZTITLE1
    folder: str | None
    created: datetime
    modified: datetime

@dataclass
class NoteSummary:
    total_count: int
    folder_counts: dict[str, int]
```

Apple timestamps (seconds since 2001-01-01) converted to `datetime` in db layer.

## Display (`display.py`)

Rich-based terminal output with no data truncation.

### Functions

- `display_notes_table(notes) -> None`: Render notes as table
- `display_count(summary) -> None`: Display counts, optionally by folder
- `display_error(message) -> None`: Red error output
- `display_success(message) -> None`: Green success output

### Table Format

```
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ ID ┃ Title                 ┃ Folder    ┃ Created    ┃ Modified   ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 1  │ Shopping List         │ Personal  │ 2025-01-15 │ 2025-01-28 │
└────┴───────────────────────┴───────────┴────────────┴────────────┘
```

Dates formatted as ISO 8601 (YYYY-MM-DD HH:MM).

## CLI (`cli.py`)

Thin layer wiring db, models, and display.

### Commands

```bash
noted list [--folder NAME] [--limit N]   # List all notes
noted count [--by-folder]                 # Count total notes
noted refresh                             # Force cache refresh
```

### Implementation Pattern

Each command:
1. Get connection (caching transparent)
2. Query data
3. Display results

## Project Setup

### Dependencies

- typer >= 0.15
- rich >= 13
- loguru >= 0.7

### Entry Point

```bash
uv run noted <command>
```

## Design Decisions

1. **Cached copy vs live DB**: Safety over convenience; CLAUDE.md requires not operating on live DB
2. **Staleness by mtime**: Simple, reliable, avoids unnecessary copies
3. **Read-only mode**: Extra safety via SQLite URI `?mode=ro`
4. **Layered architecture**: Easy to test, reusable without CLI
5. **dataclasses for models**: Clean, typed, immutable-friendly
