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
