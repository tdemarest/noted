"""Full-text search for Apple Notes using FTS5.

This module provides deep content search capabilities by maintaining
a separate SQLite database with an FTS5 virtual table index.
"""

import sqlite3
from datetime import UTC, datetime

from loguru import logger
from rich.progress import Progress, SpinnerColumn, TextColumn

from noted import db, protobuf
from noted.models import Note, SearchResult

# FTS index location (separate from cached notes db)
FTS_INDEX_PATH = db.CACHE_DIR / "fts_index.sqlite"


def _get_fts_connection(read_only: bool = False) -> sqlite3.Connection:
    """Get a connection to the FTS index database.

    Args:
        read_only: If True, open in read-only mode.

    Returns:
        SQLite connection to the FTS index database.
    """
    db.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if read_only:
        conn = sqlite3.connect(f"file:{FTS_INDEX_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(FTS_INDEX_PATH)

    conn.row_factory = sqlite3.Row
    return conn


def _index_exists() -> bool:
    """Check if the FTS index file exists.

    Returns:
        True if the index file exists.
    """
    return FTS_INDEX_PATH.exists()


def _cached_db_mtime() -> float:
    """Get modification time of the cached notes database.

    Returns:
        Modification time as Unix timestamp.

    Raises:
        FileNotFoundError: If cached database doesn't exist.
    """
    cached_db = db.CACHE_DIR / "NoteStore.sqlite"
    return cached_db.stat().st_mtime


def _index_is_fresh() -> bool:
    """Check if the FTS index is up to date with the cached database.

    Compares the stored cached mtime in the index metadata with the
    current cached database modification time. The FTS index is built
    from the cached database, so we track that mtime (not the live source).

    Returns:
        True if the index exists and is at least as new as the cached db.
    """
    if not _index_exists():
        return False

    try:
        cached_mtime = _cached_db_mtime()

        conn = _get_fts_connection(read_only=True)
        cursor = conn.execute("SELECT value FROM fts_metadata WHERE key = 'cached_mtime'")
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return False

        stored_mtime = float(row["value"])
        return stored_mtime >= cached_mtime
    except (FileNotFoundError, sqlite3.OperationalError):
        return False


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the FTS5 schema if it doesn't exist.

    Args:
        conn: Database connection to the FTS index.
    """
    # Create FTS5 virtual table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            note_id UNINDEXED,
            identifier UNINDEXED,
            title,
            folder,
            content,
            tokenize='porter unicode61'
        )
    """)

    # Create metadata table for tracking freshness
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fts_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()


def clear_index() -> None:
    """Delete the FTS index file to force a rebuild."""
    if FTS_INDEX_PATH.exists():
        FTS_INDEX_PATH.unlink()
        logger.info("FTS index cleared")


def build_index(notes_conn: sqlite3.Connection, show_progress: bool = True) -> int:
    """Build or rebuild the FTS5 search index.

    Reads all notes from the cached database, parses their content,
    and indexes them in the FTS5 virtual table.

    Args:
        notes_conn: Connection to the cached notes database.
        show_progress: If True, show a progress bar during indexing.

    Returns:
        Number of notes indexed.
    """
    # Clear existing index
    clear_index()

    # Create new index database
    fts_conn = _get_fts_connection()
    _create_schema(fts_conn)

    # Get all notes (including deleted for complete index)
    notes = db.get_all_notes(notes_conn, include_deleted=True)
    indexed_count = 0
    skipped_locked = 0

    if show_progress:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Indexing notes... 0/{len(notes)}",
                total=len(notes),
            )

            for note in notes:
                result = _index_note(fts_conn, notes_conn, note)
                if result == "indexed":
                    indexed_count += 1
                elif result == "locked":
                    skipped_locked += 1

                progress.update(
                    task,
                    advance=1,
                    description=f"Indexing notes... {indexed_count}/{len(notes)}",
                )
    else:
        for note in notes:
            result = _index_note(fts_conn, notes_conn, note)
            if result == "indexed":
                indexed_count += 1
            elif result == "locked":
                skipped_locked += 1

    # Store metadata - track cached db mtime (what we indexed from)
    cached_mtime = _cached_db_mtime()
    now = datetime.now(UTC).isoformat()

    fts_conn.execute(
        "INSERT OR REPLACE INTO fts_metadata (key, value) VALUES (?, ?)",
        ("cached_mtime", str(cached_mtime)),
    )
    fts_conn.execute(
        "INSERT OR REPLACE INTO fts_metadata (key, value) VALUES (?, ?)",
        ("built_at", now),
    )
    fts_conn.execute(
        "INSERT OR REPLACE INTO fts_metadata (key, value) VALUES (?, ?)",
        ("note_count", str(indexed_count)),
    )

    fts_conn.commit()
    fts_conn.close()

    logger.info(f"Indexed {indexed_count} notes ({skipped_locked} locked, skipped)")
    return indexed_count


def _index_note(
    fts_conn: sqlite3.Connection,
    notes_conn: sqlite3.Connection,
    note: Note,
) -> str:
    """Index a single note into the FTS table.

    Args:
        fts_conn: Connection to the FTS index database.
        notes_conn: Connection to the cached notes database.
        note: The note to index.

    Returns:
        "indexed" if successful, "locked" if note is locked, "error" on failure.
    """
    try:
        # Get note content
        raw_data = db.get_note_content(notes_conn, note.id)

        if raw_data is None:
            return "error"

        # Check if locked
        if protobuf.is_note_locked(raw_data):
            return "locked"

        # Parse content (without formatting, just need text)
        content = protobuf.parse_note_data(raw_data, include_formatting=False)
        text = content.text or ""

        # Insert into FTS table
        fts_conn.execute(
            """
            INSERT INTO notes_fts (note_id, identifier, title, folder, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (note.id, note.identifier, note.title, note.folder or "", text),
        )

        return "indexed"
    except Exception as e:
        logger.debug(f"Failed to index note {note.id}: {e}")
        return "error"


def _ensure_index(notes_conn: sqlite3.Connection) -> None:
    """Ensure the FTS index exists and is fresh.

    Builds the index if it doesn't exist or is stale.

    Args:
        notes_conn: Connection to the cached notes database.
    """
    if not _index_is_fresh():
        logger.info("FTS index is stale or missing, rebuilding...")
        build_index(notes_conn, show_progress=True)


def search_notes(
    notes_conn: sqlite3.Connection,
    query: str,
    folder: str | None = None,
    limit: int | None = None,
) -> list[SearchResult]:
    """Search notes using FTS5 full-text search.

    Searches note content, title, and folder using SQLite FTS5.
    Supports FTS5 query syntax including:
    - Simple terms: budget
    - Phrases: "project deadline"
    - Boolean: budget AND Q2
    - Prefix: budg*

    Args:
        notes_conn: Connection to the cached notes database.
        query: The search query (FTS5 syntax supported).
        folder: Optional folder filter (case-insensitive partial match).
        limit: Maximum number of results to return.

    Returns:
        List of SearchResult objects sorted by relevance.
    """
    # Ensure index is fresh
    _ensure_index(notes_conn)

    fts_conn = _get_fts_connection(read_only=True)

    try:
        # Build search query
        sql = """
            SELECT
                note_id,
                identifier,
                title,
                folder,
                snippet(notes_fts, 4, '<<<', '>>>', '...', 32) as snippet,
                rank
            FROM notes_fts
            WHERE notes_fts MATCH ?
        """
        params: list[str | int] = [query]

        if folder is not None:
            sql += " AND folder LIKE ?"
            params.append(f"%{folder}%")

        sql += " ORDER BY rank"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        cursor = fts_conn.execute(sql, params)
        results: list[SearchResult] = []

        for row in cursor:
            # Get full note metadata from notes database
            note = db.get_note_by_id(notes_conn, row["note_id"])
            if note is None:
                continue

            results.append(
                SearchResult(
                    note=note,
                    snippet=row["snippet"] or "",
                    rank=row["rank"],
                )
            )

        return results

    except sqlite3.OperationalError as e:
        # Handle FTS5 syntax errors gracefully
        # Common errors: "fts5: syntax error", "unterminated string", etc.
        error_msg = str(e).lower()
        fts_error_keywords = ["fts5", "syntax", "unterminated", "malformed"]
        if any(keyword in error_msg for keyword in fts_error_keywords):
            logger.warning(f"Invalid FTS5 query syntax: {query}")
            return []
        raise
    finally:
        fts_conn.close()


def get_index_status() -> dict[str, str | int | bool]:
    """Get status information about the FTS index.

    Returns:
        Dictionary with index status information:
        - exists: Whether the index file exists
        - fresh: Whether the index is up to date
        - note_count: Number of indexed notes (if exists)
        - built_at: When the index was built (if exists)
        - size_bytes: Size of the index file (if exists)
    """
    status: dict[str, str | int | bool] = {
        "exists": _index_exists(),
        "fresh": _index_is_fresh(),
    }

    if _index_exists():
        status["size_bytes"] = FTS_INDEX_PATH.stat().st_size

        try:
            conn = _get_fts_connection(read_only=True)
            cursor = conn.execute("SELECT key, value FROM fts_metadata")
            for row in cursor:
                if row["key"] == "note_count":
                    status["note_count"] = int(row["value"])
                elif row["key"] == "built_at":
                    status["built_at"] = row["value"]
            conn.close()
        except sqlite3.OperationalError:
            pass

    return status
