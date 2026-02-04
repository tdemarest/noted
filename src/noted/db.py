"""Database operations for Apple Notes.

Handles copying, caching, and querying the Notes SQLite database.
"""

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger

from noted.models import DatabaseStats, Note, NoteSummary


@dataclass
class FolderInfo:
    """Information about a notes folder.

    Attributes:
        name: Folder name.
        identifier: Folder UUID.
        note_count: Number of notes in folder.
        path: Full path from root (e.g., "Hobbies/Photography/Landscape Photos").
        folder_type: Folder type (0=regular, 1=system, 2=smart).
    """

    name: str
    identifier: str
    note_count: int
    path: str = ""
    folder_type: int = 0


# Apple Notes database location
NOTES_DIR = Path.home() / "Library/Group Containers/group.com.apple.notes"

# Cache location for copied database
CACHE_DIR = Path.home() / ".cache/noted"

# Files that make up the SQLite database
DB_FILES = ["NoteStore.sqlite", "NoteStore.sqlite-shm", "NoteStore.sqlite-wal"]

# Apple Core Data epoch: 2001-01-01 00:00:00 UTC
# To convert to Unix timestamp: unix_ts = apple_ts + 978307200
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def apple_timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert Apple Core Data timestamp to datetime.

    Apple Core Data stores timestamps as seconds since 2001-01-01 00:00:00 UTC.
    The offset from Unix epoch (1970-01-01) to Apple epoch (2001-01-01) is
    978307200 seconds. This function uses datetime arithmetic instead of
    the offset for clarity.

    Args:
        timestamp: Apple timestamp in seconds since 2001-01-01, or None.

    Returns:
        datetime in UTC, or None if input was None.
    """
    if timestamp is None:
        return None
    return APPLE_EPOCH + timedelta(seconds=timestamp)


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
    search: str | None = None,
) -> list[Note]:
    """Query notes from the database.

    Args:
        conn: Database connection.
        folder: Filter by folder name, or None for all.
        limit: Maximum number of notes to return, or None for all.
        search: Case-insensitive search term to filter by title or folder.

    Returns:
        List of Note objects sorted by modification date (newest first).
    """
    query = """
        SELECT
            n.Z_PK as id,
            n.ZIDENTIFIER as identifier,
            n.ZTITLE1 as title,
            f.ZTITLE2 as folder,
            n.ZCREATIONDATE3 as created,
            n.ZMODIFICATIONDATE1 as modified,
            n.ZHASCHECKLIST as has_checklist,
            n.ZHASCHECKLISTINPROGRESS as checklist_in_progress,
            n.ZISPASSWORDPROTECTED as is_locked
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
        WHERE n.ZTITLE1 IS NOT NULL
          AND n.ZMARKEDFORDELETION != 1
    """
    params: list[str | int] = []

    if folder is not None:
        query += " AND f.ZTITLE2 = ?"
        params.append(folder)

    if search is not None:
        # Case-insensitive search on title and folder
        query += " AND (n.ZTITLE1 LIKE ? COLLATE NOCASE OR f.ZTITLE2 LIKE ? COLLATE NOCASE)"
        search_pattern = f"%{search}%"
        params.append(search_pattern)
        params.append(search_pattern)

    query += " ORDER BY n.ZMODIFICATIONDATE1 DESC"

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    cursor = conn.execute(query, params)
    notes = []
    for row in cursor:
        has_checklist = bool(row["has_checklist"])
        checklist_in_progress = bool(row["checklist_in_progress"])
        notes.append(
            Note(
                id=row["id"],
                identifier=row["identifier"] or "",
                title=row["title"] or "(Untitled)",
                folder=row["folder"],
                created=apple_timestamp_to_datetime(row["created"]),
                modified=apple_timestamp_to_datetime(row["modified"]),
                has_checklist=has_checklist,
                checklist_complete=has_checklist and not checklist_in_progress,
                is_locked=bool(row["is_locked"]),
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


def get_database_stats(conn: sqlite3.Connection, by_folder: bool = False) -> DatabaseStats:
    """Get comprehensive statistics about the notes database.

    Queries multiple aspects of the database to build a complete picture:
    - Note counts (total, pinned, locked, deleted, checklists)
    - Folder breakdown (optional)
    - Attachment type distribution
    - Location-tagged attachments

    Args:
        conn: Database connection.
        by_folder: Whether to include per-folder counts.

    Returns:
        DatabaseStats with all statistics populated.
    """
    # Total notes (non-deleted)
    total_notes = count_notes(conn)

    # Pinned notes
    cursor = conn.execute("""
        SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE1 IS NOT NULL AND ZISPINNED = 1 AND ZMARKEDFORDELETION != 1
    """)
    pinned_notes = cursor.fetchone()[0]

    # Locked notes (password-protected)
    cursor = conn.execute("""
        SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE1 IS NOT NULL AND ZISPASSWORDPROTECTED = 1
    """)
    locked_notes = cursor.fetchone()[0]

    # Deleted notes
    cursor = conn.execute("""
        SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE1 IS NOT NULL AND ZMARKEDFORDELETION = 1
    """)
    deleted_notes = cursor.fetchone()[0]

    # Notes with checklists
    cursor = conn.execute("""
        SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE1 IS NOT NULL AND ZHASCHECKLIST = 1 AND ZMARKEDFORDELETION != 1
    """)
    notes_with_checklists = cursor.fetchone()[0]

    # Notes with incomplete checklists
    cursor = conn.execute("""
        SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE1 IS NOT NULL AND ZHASCHECKLISTINPROGRESS = 1 AND ZMARKEDFORDELETION != 1
    """)
    notes_with_incomplete_checklists = cursor.fetchone()[0]

    # Folder counts (optional)
    folder_counts: dict[str, int] = {}
    if by_folder:
        cursor = conn.execute("""
            SELECT
                COALESCE(f.ZTITLE2, '(No Folder)') as folder,
                COUNT(*) as count
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
            WHERE n.ZTITLE1 IS NOT NULL
              AND n.ZMARKEDFORDELETION != 1
            GROUP BY f.ZTITLE2
            ORDER BY count DESC
        """)
        for row in cursor:
            folder_counts[row["folder"]] = row["count"]

    # Attachment type distribution
    cursor = conn.execute("""
        SELECT ZTYPEUTI, COUNT(*) as count
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTYPEUTI IS NOT NULL
        GROUP BY ZTYPEUTI
        ORDER BY count DESC
    """)
    attachment_type_counts: dict[str, int] = {}
    total_attachments = 0
    for row in cursor:
        attachment_type_counts[row["ZTYPEUTI"]] = row["count"]
        total_attachments += row["count"]

    # Attachments with location data
    cursor = conn.execute("SELECT COUNT(*) FROM ZICLOCATION")
    attachments_with_location = cursor.fetchone()[0]

    # Database file size and modification time (cached copy)
    cached_db = CACHE_DIR / "NoteStore.sqlite"
    if cached_db.exists():
        db_stat = cached_db.stat()
        database_size_bytes = db_stat.st_size
        cache_modified = datetime.fromtimestamp(db_stat.st_mtime, tz=UTC)
    else:
        database_size_bytes = 0
        cache_modified = None

    # FTS index status (import here to avoid circular import)
    from noted import search

    fts_status = search.get_index_status()
    fts_index_size_bytes = int(fts_status.get("size_bytes", 0))
    fts_index_built_at = fts_status.get("built_at")
    if isinstance(fts_index_built_at, int):
        fts_index_built_at = None
    fts_index_fresh = bool(fts_status.get("fresh", False))
    fts_indexed_notes = int(fts_status.get("note_count", 0))

    return DatabaseStats(
        total_notes=total_notes,
        pinned_notes=pinned_notes,
        locked_notes=locked_notes,
        deleted_notes=deleted_notes,
        notes_with_checklists=notes_with_checklists,
        notes_with_incomplete_checklists=notes_with_incomplete_checklists,
        folder_counts=folder_counts,
        total_attachments=total_attachments,
        attachment_type_counts=attachment_type_counts,
        attachments_with_location=attachments_with_location,
        database_size_bytes=database_size_bytes,
        cache_modified=cache_modified,
        fts_index_size_bytes=fts_index_size_bytes,
        fts_index_built_at=fts_index_built_at,
        fts_index_fresh=fts_index_fresh,
        fts_indexed_notes=fts_indexed_notes,
    )


def get_note_content(conn: sqlite3.Connection, note_id: int) -> bytes | None:
    """Fetch raw ZDATA bytes for a note by row ID.

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


def get_note_content_by_identifier(conn: sqlite3.Connection, identifier: str) -> bytes | None:
    """Fetch raw ZDATA bytes for a note by UUID identifier.

    Args:
        conn: Database connection.
        identifier: The ZIDENTIFIER (UUID) of the note.

    Returns:
        Raw gzip-compressed protobuf bytes, or None if not found.
    """
    query = """
        SELECT nd.ZDATA
        FROM ZICCLOUDSYNCINGOBJECT n
        JOIN ZICNOTEDATA nd ON nd.ZNOTE = n.Z_PK
        WHERE n.ZIDENTIFIER = ?
    """
    cursor = conn.execute(query, (identifier,))
    row = cursor.fetchone()
    if row is None:
        return None
    return row["ZDATA"]


def get_note_by_id(conn: sqlite3.Connection, note_id: int) -> Note | None:
    """Fetch a single note by its database row ID.

    Args:
        conn: Database connection.
        note_id: The Z_PK of the note.

    Returns:
        Note object, or None if not found.
    """
    query = """
        SELECT
            n.Z_PK as id,
            n.ZIDENTIFIER as identifier,
            n.ZTITLE1 as title,
            f.ZTITLE2 as folder,
            n.ZCREATIONDATE3 as created,
            n.ZMODIFICATIONDATE1 as modified
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
        identifier=row["identifier"] or "",
        title=row["title"] or "(Untitled)",
        folder=row["folder"],
        created=apple_timestamp_to_datetime(row["created"]),
        modified=apple_timestamp_to_datetime(row["modified"]),
    )


def get_note_by_identifier(conn: sqlite3.Connection, identifier: str) -> Note | None:
    """Fetch a single note by its UUID identifier.

    Args:
        conn: Database connection.
        identifier: The ZIDENTIFIER (UUID) of the note.

    Returns:
        Note object, or None if not found.
    """
    query = """
        SELECT
            n.Z_PK as id,
            n.ZIDENTIFIER as identifier,
            n.ZTITLE1 as title,
            f.ZTITLE2 as folder,
            n.ZCREATIONDATE3 as created,
            n.ZMODIFICATIONDATE1 as modified
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
        WHERE n.ZIDENTIFIER = ?
          AND n.ZTITLE1 IS NOT NULL
          AND n.ZMARKEDFORDELETION != 1
    """
    cursor = conn.execute(query, (identifier,))
    row = cursor.fetchone()
    if row is None:
        return None
    return Note(
        id=row["id"],
        identifier=row["identifier"] or "",
        title=row["title"] or "(Untitled)",
        folder=row["folder"],
        created=apple_timestamp_to_datetime(row["created"]),
        modified=apple_timestamp_to_datetime(row["modified"]),
    )


def get_note(conn: sqlite3.Connection, note_ref: str) -> Note | None:
    """Fetch a note by either row ID or UUID identifier.

    Accepts either a numeric row ID or a UUID string.

    Args:
        conn: Database connection.
        note_ref: Either a numeric ID (e.g., "42") or UUID
            (e.g., "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE").

    Returns:
        Note object, or None if not found.
    """
    # Try parsing as integer first
    try:
        note_id = int(note_ref)
        return get_note_by_id(conn, note_id)
    except ValueError:
        # Not an integer, try as UUID
        return get_note_by_identifier(conn, note_ref)


def get_all_notes(
    conn: sqlite3.Connection,
    folder: str | None = None,
    include_deleted: bool = True,
) -> list[Note]:
    """Fetch all notes from the database with full folder paths.

    Unlike list_notes(), this function can include deleted notes
    and is intended for full export operations. Returns full folder
    paths (e.g., "Hobbies/Photography/Landscape Photos") instead
    of just the immediate folder name.

    Args:
        conn: Database connection.
        folder: Filter by folder name (matches anywhere in path), or None for all.
        include_deleted: If True, include notes marked for deletion.

    Returns:
        List of Note objects sorted by folder path then modification date.
    """
    # Get folder paths lookup first
    folder_paths = get_folder_paths(conn)

    query = """
        SELECT
            n.Z_PK as id,
            n.ZIDENTIFIER as identifier,
            n.ZTITLE1 as title,
            n.ZFOLDER as folder_id,
            f.ZTITLE2 as folder_name,
            n.ZCREATIONDATE3 as created,
            n.ZMODIFICATIONDATE1 as modified,
            n.ZMARKEDFORDELETION as deleted
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
        WHERE n.ZTITLE1 IS NOT NULL
    """
    params: list[str | int] = []

    if not include_deleted:
        query += " AND (n.ZMARKEDFORDELETION IS NULL OR n.ZMARKEDFORDELETION != 1)"

    query += " ORDER BY f.ZTITLE2, n.ZMODIFICATIONDATE1 DESC"

    cursor = conn.execute(query, params)
    notes = []
    for row in cursor:
        # For deleted notes, show "Recently Deleted" as folder
        if row["deleted"] and row["deleted"] == 1:
            folder_path = "Recently Deleted"
        elif row["folder_id"]:
            # Use full folder path from lookup
            folder_path = folder_paths.get(row["folder_id"], row["folder_name"])
        else:
            folder_path = row["folder_name"]

        # Apply folder filter (matches if filter appears anywhere in path)
        if folder is not None and folder.lower() not in (folder_path or "").lower():
            continue

        notes.append(
            Note(
                id=row["id"],
                identifier=row["identifier"] or "",
                title=row["title"] or "(Untitled)",
                folder=folder_path,
                created=apple_timestamp_to_datetime(row["created"]),
                modified=apple_timestamp_to_datetime(row["modified"]),
            )
        )

    # Sort by folder path for proper hierarchy grouping
    return sorted(notes, key=lambda n: (n.folder or "", n.modified or datetime.min), reverse=False)


def get_folder_paths(conn: sqlite3.Connection) -> dict[int, str]:
    """Build a lookup table of folder Z_PK to full path.

    Handles nested folder hierarchy by following ZPARENT chain.
    For example: "Hobbies/Photography/Landscape Photos"

    Args:
        conn: Database connection.

    Returns:
        Dictionary mapping folder Z_PK to full path string.
    """
    # Get all folders with their parent info
    query = """
        SELECT
            Z_PK as id,
            ZTITLE2 as name,
            ZPARENT as parent_id
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZTITLE2 IS NOT NULL
    """
    cursor = conn.execute(query)

    # Build lookup tables
    folder_names: dict[int, str] = {}
    folder_parents: dict[int, int | None] = {}

    for row in cursor:
        folder_id = row["id"]
        folder_names[folder_id] = row["name"]
        folder_parents[folder_id] = row["parent_id"]

    # Build full paths by following parent chain
    folder_paths: dict[int, str] = {}

    def build_path(folder_id: int) -> str:
        if folder_id in folder_paths:
            return folder_paths[folder_id]

        name = folder_names.get(folder_id, "")
        parent_id = folder_parents.get(folder_id)

        if parent_id is None or parent_id not in folder_names:
            # Root folder
            folder_paths[folder_id] = name
        else:
            # Has parent - recursively build parent path
            parent_path = build_path(parent_id)
            folder_paths[folder_id] = f"{parent_path}/{name}"

        return folder_paths[folder_id]

    # Build paths for all folders
    for folder_id in folder_names:
        build_path(folder_id)

    return folder_paths


def get_folders(conn: sqlite3.Connection) -> list[FolderInfo]:
    """Get all folders with their note counts and full paths.

    Args:
        conn: Database connection.

    Returns:
        List of FolderInfo objects sorted by path.
    """
    # Get folder paths first
    folder_paths = get_folder_paths(conn)

    # Check if ZFOLDERTYPE column exists (may not in test fixtures)
    cursor = conn.execute("PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)")
    columns = {row[1] for row in cursor.fetchall()}
    has_folder_type = "ZFOLDERTYPE" in columns

    if has_folder_type:
        query = """
            SELECT
                f.Z_PK as id,
                f.ZTITLE2 as name,
                f.ZIDENTIFIER as identifier,
                COALESCE(f.ZFOLDERTYPE, 0) as folder_type,
                COUNT(n.Z_PK) as note_count
            FROM ZICCLOUDSYNCINGOBJECT f
            LEFT JOIN ZICCLOUDSYNCINGOBJECT n ON n.ZFOLDER = f.Z_PK
                AND n.ZTITLE1 IS NOT NULL
            WHERE f.ZTITLE2 IS NOT NULL
            GROUP BY f.Z_PK, f.ZTITLE2, f.ZIDENTIFIER, f.ZFOLDERTYPE
            ORDER BY f.ZTITLE2
        """
    else:
        query = """
            SELECT
                f.Z_PK as id,
                f.ZTITLE2 as name,
                f.ZIDENTIFIER as identifier,
                0 as folder_type,
                COUNT(n.Z_PK) as note_count
            FROM ZICCLOUDSYNCINGOBJECT f
            LEFT JOIN ZICCLOUDSYNCINGOBJECT n ON n.ZFOLDER = f.Z_PK
                AND n.ZTITLE1 IS NOT NULL
            WHERE f.ZTITLE2 IS NOT NULL
            GROUP BY f.Z_PK, f.ZTITLE2, f.ZIDENTIFIER
            ORDER BY f.ZTITLE2
        """

    cursor = conn.execute(query)
    folders = [
        FolderInfo(
            name=row["name"],
            identifier=row["identifier"] or "",
            note_count=row["note_count"],
            path=folder_paths.get(row["id"], row["name"]),
            folder_type=row["folder_type"],
        )
        for row in cursor
    ]
    # Sort by full path for proper hierarchy ordering
    return sorted(folders, key=lambda f: f.path.lower())


def get_all_attachment_types(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    """Get attachment type counts for all notes.

    Queries all notes and their attachments, grouping by note ID and UTI type.

    Args:
        conn: Database connection.

    Returns:
        Mapping of note_id (Z_PK) to {UTI type: count}.
        Notes without attachments are not included.
    """
    query = """
        SELECT
            att.ZNOTE as note_id,
            att.ZTYPEUTI as type_uti,
            COUNT(*) as count
        FROM ZICCLOUDSYNCINGOBJECT att
        WHERE att.ZNOTE IS NOT NULL
          AND att.ZTYPEUTI IS NOT NULL
        GROUP BY att.ZNOTE, att.ZTYPEUTI
    """
    cursor = conn.execute(query)

    result: dict[int, dict[str, int]] = {}
    for row in cursor:
        note_id = row["note_id"]
        type_uti = row["type_uti"]
        count = row["count"]
        if note_id not in result:
            result[note_id] = {}
        result[note_id][type_uti] = count

    return result


def get_attachment_names(conn: sqlite3.Connection, note_id: int) -> dict[str, str]:
    """Fetch attachment identifiers and titles for a note.

    Args:
        conn: Database connection.
        note_id: The Z_PK of the note.

    Returns:
        Mapping of attachment identifier (UUID) to title/filename/alttext.
        Uses ZTITLE if available, falls back to ZALTTEXT (for hashtags).
        Checks both ZNOTE and ZNOTE1 columns for linkage.
    """
    # Check if ZALTTEXT column exists (may not in test fixtures)
    cursor = conn.execute("PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)")
    columns = {row[1] for row in cursor.fetchall()}
    has_alttext = "ZALTTEXT" in columns
    has_znote1 = "ZNOTE1" in columns

    if has_alttext and has_znote1:
        query = """
            SELECT ZIDENTIFIER, COALESCE(ZTITLE, ZALTTEXT) as name
            FROM ZICCLOUDSYNCINGOBJECT
            WHERE (ZNOTE = ? OR ZNOTE1 = ?)
              AND ZIDENTIFIER IS NOT NULL
              AND (ZTITLE IS NOT NULL OR ZALTTEXT IS NOT NULL)
        """
        cursor = conn.execute(query, (note_id, note_id))
    elif has_alttext:
        query = """
            SELECT ZIDENTIFIER, COALESCE(ZTITLE, ZALTTEXT) as name
            FROM ZICCLOUDSYNCINGOBJECT
            WHERE ZNOTE = ?
              AND ZIDENTIFIER IS NOT NULL
              AND (ZTITLE IS NOT NULL OR ZALTTEXT IS NOT NULL)
        """
        cursor = conn.execute(query, (note_id,))
    else:
        query = """
            SELECT ZIDENTIFIER, ZTITLE as name
            FROM ZICCLOUDSYNCINGOBJECT
            WHERE ZNOTE = ?
              AND ZIDENTIFIER IS NOT NULL
              AND ZTITLE IS NOT NULL
        """
        cursor = conn.execute(query, (note_id,))
    return {row["ZIDENTIFIER"]: row["name"] for row in cursor}


def get_attachment_stats(conn: sqlite3.Connection, note_id: int) -> dict[str, int | float]:
    """Get attachment count and total size for a note.

    Queries the database for all attachments linked to a note and calculates
    total file size by checking actual files on disk. The ZFILESIZE column
    in the database is often unpopulated, so we stat the files directly.

    Args:
        conn: Database connection.
        note_id: The Z_PK of the note.

    Returns:
        Dictionary with 'count' (int) and 'total_size' (int, bytes).
    """
    # Get all attachments with their media info
    query = """
        SELECT
            att.ZIDENTIFIER as att_id,
            att.ZTYPEUTI as type_uti,
            media.ZIDENTIFIER as media_id,
            media.ZFILENAME as filename
        FROM ZICCLOUDSYNCINGOBJECT att
        LEFT JOIN ZICCLOUDSYNCINGOBJECT media ON att.ZMEDIA = media.Z_PK
        WHERE att.ZNOTE = ?
          AND att.ZIDENTIFIER IS NOT NULL
          AND att.ZTYPEUTI IS NOT NULL
    """
    cursor = conn.execute(query, (note_id,))
    rows = cursor.fetchall()

    count = len(rows)
    total_size = 0

    # Calculate total size from actual files on disk
    for row in rows:
        media_id = row["media_id"]
        filename = row["filename"]
        if media_id and filename:
            file_path = _find_media_file(media_id, filename)
            if file_path:
                try:
                    total_size += file_path.stat().st_size
                except OSError:
                    pass  # File not accessible, skip

    return {
        "count": count,
        "total_size": total_size,
    }


def get_table_data(conn: sqlite3.Connection, identifier: str) -> tuple[bytes, str] | None:
    """Fetch ZMERGEABLEDATA1 and ZSUMMARY for a table attachment by identifier.

    Args:
        conn: Database connection.
        identifier: The attachment's unique identifier (UUID).

    Returns:
        Tuple of (raw gzipped protobuf bytes, summary text), or None if not found.
        The summary contains column headers in display order.
    """
    query = """
        SELECT ZMERGEABLEDATA1, ZSUMMARY
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZIDENTIFIER = ?
          AND ZMERGEABLEDATA1 IS NOT NULL
    """
    cursor = conn.execute(query, (identifier,))
    row = cursor.fetchone()
    if row is None:
        return None
    return (row["ZMERGEABLEDATA1"], row["ZSUMMARY"] or "")


def _find_media_file(media_identifier: str, filename: str) -> Path | None:
    """Find a media file on disk by its identifier and filename.

    Apple Notes stores attachments on disk, not in the database.
    The path structure is:
    NOTES_DIR/Accounts/<ACCOUNT_UUID>/Media/<MEDIA_ID>/<subfolder>/<filename>

    Args:
        media_identifier: The media record's ZIDENTIFIER (UUID).
        filename: The filename from ZFILENAME.

    Returns:
        Path to the file if found, None otherwise.
    """
    accounts_dir = NOTES_DIR / "Accounts"
    if not accounts_dir.exists():
        return None

    # Search through all account folders
    for account_dir in accounts_dir.iterdir():
        if not account_dir.is_dir():
            continue
        media_dir = account_dir / "Media" / media_identifier
        if not media_dir.exists():
            continue

        # The file is in a subfolder (usually named 1_<UUID>)
        for subfolder in media_dir.iterdir():
            if not subfolder.is_dir():
                continue
            file_path = subfolder / filename
            if file_path.exists():
                return file_path

    return None


def get_attachment_data(
    conn: sqlite3.Connection,
    identifier: str,
) -> tuple[bytes, str, str | None] | None:
    """Fetch binary data for an attachment by identifier.

    Apple Notes stores attachment files on disk, not in the database.
    This function queries the database for file location info, then
    reads the file from disk.

    Args:
        conn: Database connection.
        identifier: The attachment's unique identifier (UUID).

    Returns:
        Tuple of (binary_data, type_uti, title), or None if not found
        or attachment has no binary data on disk.
    """
    # Get attachment info and the linked media record
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
    cursor = conn.execute(query, (identifier,))
    row = cursor.fetchone()
    if row is None:
        return None

    type_uti = row["ZTYPEUTI"]
    att_title = row["att_title"]
    media_id = row["media_id"]
    filename = row["ZFILENAME"]

    # If no media record or filename, can't find file
    if not media_id or not filename:
        return None

    # Find the file on disk
    file_path = _find_media_file(media_id, filename)
    if file_path is None:
        return None

    # Read and return file contents
    try:
        binary_data = file_path.read_bytes()
        return (binary_data, type_uti, att_title or filename)
    except OSError:
        return None
