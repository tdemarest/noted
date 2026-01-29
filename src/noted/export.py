"""Full export functionality for Apple Notes.

Handles exporting all notes to a structured folder hierarchy
with master index and optional 7zip compression.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from noted import attachments, db, display, protobuf, tables
from noted.models import Note


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


def generate_locked_placeholder(note: Note) -> str:
    """Generate markdown content for a locked note placeholder.

    Args:
        note: The locked note's metadata.

    Returns:
        Markdown content explaining the note is locked.
    """
    return f"""# {note.title}

> **This note is locked and cannot be exported.**
>
> To export this note, unlock it in Apple Notes and run the export again.

---
*Note ID: {note.id}*
*Identifier: {note.identifier}*
*Folder: {note.folder or "(No Folder)"}*
"""


def make_unique_folder_name(
    folder_name: str,
    identifier: str,
    used_names: set[str],
) -> str:
    """Generate a unique folder name, adding UUID suffix if needed.

    Args:
        folder_name: Desired folder name.
        identifier: Note UUID for suffix if conflict.
        used_names: Set of already-used names (modified in place).

    Returns:
        Unique folder name (original or with UUID suffix).
    """
    if folder_name not in used_names:
        used_names.add(folder_name)
        return folder_name

    # Add UUID suffix
    unique = f"{folder_name}_{identifier[:6]}"
    used_names.add(unique)
    return unique


def generate_master_index(
    index_path: Path,
    result: FullExportResult,
    folder_info: list[dict[str, str | int]],
) -> None:
    """Generate master index.json for full export.

    Args:
        index_path: Path to write index.json.
        result: Export result with statistics and note list.
        folder_info: List of folder info dicts with name, path, note_count.
    """
    notes_data = []
    for note_result in result.notes:
        notes_data.append(
            {
                "id": note_result.note_id,
                "identifier": note_result.identifier,
                "title": note_result.title,
                "folder": note_result.folder,
                "path": str(note_result.path) if note_result.path else None,
                "attachment_count": note_result.attachment_count,
                "locked": note_result.status == "locked",
                "export_status": note_result.status,
            }
        )

    errors_data = []
    for error in result.errors:
        errors_data.append(
            {
                "note_id": error.note_id,
                "identifier": error.identifier,
                "title": error.title,
                "folder": error.folder,
                "error": error.error,
            }
        )

    index = {
        "export_version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "source": "Apple Notes",
        "statistics": {
            "total_notes": result.total_notes,
            "exported_count": result.exported_count,
            "locked_count": result.locked_count,
            "failed_count": result.failed_count,
            "total_attachments": result.total_attachments,
            "total_folders": len(folder_info),
        },
        "folders": folder_info,
        "notes": notes_data,
        "errors": errors_data,
    }

    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def export_single_note(
    conn: sqlite3.Connection,
    note: Note,
    output_dir: Path,
    used_folder_names: set[str] | None = None,
) -> NoteExportResult:
    """Export a single note to the output directory.

    Creates a folder for the note containing the markdown file
    and attachments subdirectory (for full export structure).

    Args:
        conn: Database connection.
        note: Note to export.
        output_dir: Base output directory.
        used_folder_names: Set of already-used folder names for deduplication.

    Returns:
        NoteExportResult with export status and path.
    """
    if used_folder_names is None:
        used_folder_names = set()

    # Determine folder path
    folder_name = note.folder or "(No Folder)"
    folder_path = output_dir / attachments.sanitize_filename(folder_name)

    # Create note folder with unique name
    note_folder_name = attachments.sanitize_filename(note.title)
    note_folder_name = make_unique_folder_name(note_folder_name, note.identifier, used_folder_names)
    note_path = folder_path / note_folder_name

    # Get note content
    raw_data = db.get_note_content(conn, note.id)

    if raw_data is None:
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="failed",
            path=None,
            attachment_count=0,
            error="Note has no content",
        )

    # Check if locked
    if protobuf.is_note_locked(raw_data):
        # Create placeholder
        note_path.mkdir(parents=True, exist_ok=True)
        note_file = note_path / f"{note_folder_name}.md"
        note_file.write_text(generate_locked_placeholder(note), encoding="utf-8")

        relative_path = note_file.relative_to(output_dir)
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="locked",
            path=relative_path,
            attachment_count=0,
            error=None,
        )

    try:
        # Parse content
        attachment_names = db.get_attachment_names(conn, note.id)
        content = protobuf.parse_note_data(raw_data, attachment_names, include_formatting=True)

        # Parse table attachments
        if content.attachments:
            for attachment in content.attachments:
                if attachment.type_uti == "com.apple.notes.table":
                    result = db.get_table_data(conn, attachment.identifier)
                    if result:
                        table_data, summary = result
                        attachment.table = tables.parse_table_data(table_data, summary)

        # Generate markdown
        markdown_content = display.get_note_markdown(note, content)

        # Create note folder and write file
        note_path.mkdir(parents=True, exist_ok=True)
        note_file = note_path / f"{note_folder_name}.md"
        note_file.write_text(markdown_content, encoding="utf-8")

        # Export attachments
        attachment_count = 0
        if content.attachments:
            # For full export, attachments go in note_path/attachments/
            att_result = attachments.export_attachments(
                conn=conn,
                attachments=content.attachments,
                output_dir=note_path,
                base_name="attachments",
                note=note,
            )
            attachment_count = len(att_result.exported)

            # Rename attachments folder if created (remove "_attachments" suffix)
            # The export_attachments function creates "{base_name}_attachments"
            old_att_dir = note_path / "attachments_attachments"
            new_att_dir = note_path / "attachments"
            if old_att_dir.exists() and not new_att_dir.exists():
                old_att_dir.rename(new_att_dir)

        relative_path = note_file.relative_to(output_dir)
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="success",
            path=relative_path,
            attachment_count=attachment_count,
            error=None,
        )

    except Exception as e:
        return NoteExportResult(
            note_id=note.id,
            identifier=note.identifier,
            title=note.title,
            folder=note.folder,
            status="failed",
            path=None,
            attachment_count=0,
            error=str(e),
        )


def export_all_notes(
    conn: sqlite3.Connection,
    options: ExportOptions,
) -> FullExportResult:
    """Export all notes to structured folder hierarchy.

    Args:
        conn: Database connection.
        options: Export configuration.

    Returns:
        FullExportResult with statistics and note list.
    """
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
    )

    # Get all notes
    notes = db.get_all_notes(
        conn,
        folder=options.folder_filter,
        include_deleted=options.include_deleted,
    )

    # Get folder info
    folders_raw = db.get_folders(conn)
    folder_names = [f.name for f in folders_raw]

    # Create output directory
    options.output_dir.mkdir(parents=True, exist_ok=True)

    # Track results
    note_results: list[NoteExportResult] = []
    errors: list[ExportError] = []
    total_attachments = 0
    exported_count = 0
    locked_count = 0
    failed_count = 0

    # Track used folder names per parent folder for deduplication
    used_names_by_folder: dict[str, set[str]] = {}

    # Export notes with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("notes"),
        disable=options.verbose,
    ) as progress:
        task = progress.add_task("Exporting notes...", total=len(notes))

        for note in notes:
            # Get or create used names set for this folder
            folder_key = note.folder or "(No Folder)"
            if folder_key not in used_names_by_folder:
                used_names_by_folder[folder_key] = set()

            result = export_single_note(
                conn, note, options.output_dir, used_names_by_folder[folder_key]
            )
            note_results.append(result)

            if result.status == "success":
                exported_count += 1
                total_attachments += result.attachment_count
                if options.verbose:
                    att_info = (
                        f" ({result.attachment_count} attachments)"
                        if result.attachment_count
                        else ""
                    )
                    print(f"  \u2713 {note.folder or '(No Folder)'}/{note.title}{att_info}")
            elif result.status == "locked":
                locked_count += 1
                if options.verbose:
                    print(f"  \u26a0 {note.folder or '(No Folder)'}/{note.title} (locked)")
            else:
                failed_count += 1
                errors.append(
                    ExportError(
                        note_id=note.id,
                        identifier=note.identifier,
                        title=note.title,
                        folder=note.folder,
                        error=result.error or "Unknown error",
                    )
                )
                if options.verbose:
                    print(
                        f"  \u2717 {note.folder or '(No Folder)'}/{note.title} "
                        f"(failed: {result.error})"
                    )

            progress.update(task, advance=1)

    # Build folder info for index
    folder_info: list[dict[str, str | int]] = []
    for folder_name in folder_names:
        folder_path = attachments.sanitize_filename(folder_name)
        count = sum(1 for r in note_results if r.folder == folder_name)
        if count > 0:
            folder_info.append(
                {
                    "name": folder_name,
                    "path": f"{folder_path}/",
                    "note_count": count,
                }
            )

    # Add (No Folder) if any notes have no folder
    no_folder_count = sum(1 for r in note_results if r.folder is None)
    if no_folder_count > 0:
        folder_info.append(
            {
                "name": "(No Folder)",
                "path": "(No_Folder)/",
                "note_count": no_folder_count,
            }
        )

    # Build result
    full_result = FullExportResult(
        output_dir=options.output_dir,
        archive_path=None,
        total_notes=len(notes),
        exported_count=exported_count,
        locked_count=locked_count,
        failed_count=failed_count,
        total_attachments=total_attachments,
        folders=folder_names,
        notes=note_results,
        errors=errors,
    )

    # Generate master index
    index_path = options.output_dir / "index.json"
    generate_master_index(index_path, full_result, folder_info)

    # Create archive if requested
    if options.create_archive:
        archive_path = create_full_archive(options.output_dir, verbose=options.verbose)
        full_result.archive_path = archive_path

    return full_result


def create_full_archive(output_dir: Path, verbose: bool = False) -> Path:
    """Create 7zip archive of the entire export.

    Unlike single-note archive, this keeps the original files.
    Shows a progress bar during compression.

    Args:
        output_dir: Directory to archive.
        verbose: If True, disable progress bar (verbose mode shows text).

    Returns:
        Path to created .7z archive.
    """
    import py7zr
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
    )

    archive_path = output_dir.with_suffix(".7z")

    # Collect all files first for progress tracking
    files_to_archive = [f for f in output_dir.rglob("*") if f.is_file()]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("files"),
        disable=verbose,
    ) as progress:
        task = progress.add_task("Creating archive...", total=len(files_to_archive))

        with py7zr.SevenZipFile(archive_path, "w") as archive:
            for file in files_to_archive:
                arcname = str(file.relative_to(output_dir.parent))
                archive.write(file, arcname)
                progress.update(task, advance=1)

    return archive_path
