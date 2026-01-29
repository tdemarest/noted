"""Database operations for Apple Notes.

Handles copying, caching, and querying the Notes SQLite database.
"""

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
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
            n.ZIDENTIFIER as identifier,
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
                identifier=row["identifier"] or "",
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
            n.ZCREATIONDATE as created,
            n.ZMODIFICATIONDATE as modified
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


def get_attachment_names(conn: sqlite3.Connection, note_id: int) -> dict[str, str]:
    """Fetch attachment identifiers and titles for a note.

    Args:
        conn: Database connection.
        note_id: The Z_PK of the note.

    Returns:
        Mapping of attachment identifier (UUID) to title/filename.
        Only includes attachments that have a title.
    """
    query = """
        SELECT ZIDENTIFIER, ZTITLE
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE ZNOTE = ?
          AND ZIDENTIFIER IS NOT NULL
          AND ZTITLE IS NOT NULL
    """
    cursor = conn.execute(query, (note_id,))
    return {row["ZIDENTIFIER"]: row["ZTITLE"] for row in cursor}


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
