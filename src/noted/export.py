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
