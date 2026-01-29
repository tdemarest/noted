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
        created: When the note was created, or None if unknown.
        modified: When the note was last modified, or None if unknown.
    """

    id: int
    title: str
    folder: str | None
    created: datetime | None
    modified: datetime | None


@dataclass
class NoteSummary:
    """Aggregate statistics about the notes database.

    Attributes:
        total_count: Total number of notes.
        folder_counts: Mapping of folder name to note count.
    """

    total_count: int
    folder_counts: dict[str, int]


@dataclass
class Attachment:
    """Represents an embedded attachment in a note.

    Attributes:
        identifier: Unique identifier (UUID) for the attachment.
        type_uti: Uniform Type Identifier (e.g., 'public.jpeg').
        title: Display name/filename of the attachment, if known.
    """

    identifier: str
    type_uti: str
    title: str | None = None


@dataclass
class NoteContent:
    """Parsed content of an Apple Note.

    Attributes:
        text: The plain text content extracted from protobuf.
        attachments: List of embedded attachments found in the note.
    """

    text: str
    attachments: list[Attachment] | None = None
