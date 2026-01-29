"""Attachment export functionality for Apple Notes.

Handles extracting attachments from notes and exporting them to disk,
with optional 7zip compression.
"""

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import py7zr

from noted import db
from noted.models import Attachment, Note


@dataclass
class ExportedAttachment:
    """Result of exporting a single attachment.

    Attributes:
        identifier: Unique identifier (UUID) for the attachment.
        filename: Final filename used (after deduplication), or None if skipped.
        type_uti: Uniform Type Identifier (e.g., 'public.jpeg').
        exported: True if binary data was written to disk.
        skip_reason: Why it wasn't exported, or None if exported successfully.
    """

    identifier: str
    filename: str | None
    type_uti: str
    exported: bool
    skip_reason: str | None


@dataclass
class AttachmentExportResult:
    """Summary of attachment export operation.

    Attributes:
        exported: List of successfully exported attachments.
        skipped: List of attachments that were skipped.
        manifest_path: Path to manifest.json, or None if no attachments.
        attachments_dir: Path to attachments directory, or None if no attachments.
    """

    exported: list[ExportedAttachment]
    skipped: list[ExportedAttachment]
    manifest_path: Path | None
    attachments_dir: Path | None


# UTI to file extension mapping
UTI_EXTENSION_MAP: dict[str, str] = {
    "public.jpeg": ".jpg",
    "public.png": ".png",
    "public.heic": ".heic",
    "public.gif": ".gif",
    "public.tiff": ".tiff",
    "com.compuserve.gif": ".gif",
    "com.adobe.pdf": ".pdf",
    "public.pdf": ".pdf",
    "com.apple.drawing": ".png",
    "com.apple.drawing.2": ".png",
}


def uti_to_extension(uti: str) -> str:
    """Convert UTI to file extension.

    Args:
        uti: Uniform Type Identifier (e.g., 'public.jpeg').

    Returns:
        File extension with leading dot (e.g., '.jpg').
        Returns '.bin' for unknown types.
    """
    return UTI_EXTENSION_MAP.get(uti, ".bin")


def sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe filesystem use.

    Removes or replaces characters that are invalid in filenames
    on common operating systems (Windows, macOS, Linux).

    Args:
        name: Original filename.

    Returns:
        Sanitized filename safe for filesystem use.
    """
    if not name:
        return "attachment"

    # Replace spaces with underscores
    result = name.replace(" ", "_")

    # Remove characters invalid on Windows/macOS/Linux
    # Invalid: / \ : * ? " < > |
    result = re.sub(r'[/\\:*?"<>|]', "", result)

    # Remove control characters
    result = re.sub(r"[\x00-\x1f\x7f]", "", result)

    # If nothing left, use default
    if not result or result.strip(".") == "":
        return "attachment"

    return result


def make_unique_filename(
    filename: str,
    identifier: str,
    used_names: set[str],
) -> str:
    """Generate a unique filename, adding UUID suffix if needed.

    Args:
        filename: Desired filename.
        identifier: Attachment UUID for suffix if conflict.
        used_names: Set of already-used filenames (modified in place).

    Returns:
        Unique filename (original or with UUID suffix).
    """
    if filename not in used_names:
        used_names.add(filename)
        return filename

    # Split into name and extension
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        unique = f"{name}_{identifier[:6]}.{ext}"
    else:
        unique = f"{filename}_{identifier[:6]}"

    used_names.add(unique)
    return unique


# UTIs that don't have exportable binary data
NON_EXPORTABLE_UTIS: dict[str, str] = {
    "com.apple.notes.table": "Rendered inline in note content",
    "com.apple.notes.gallery": "Gallery container, no single file",
    "com.apple.notes.inlinetextattachment": "Inline text, no file data",
    "com.apple.notes.inlinetextattachment.hashtag": "Hashtag, no file data",
    "com.apple.notes.inlinetextattachment.mention": "Mention, no file data",
    "public.url": "URL link, no file data",
    "com.apple.mapkit.map-item": "Location data, no file data",
    "public.vcard": "Contact data, no file data",
}


def get_skip_reason(type_uti: str) -> str | None:
    """Get skip reason for non-exportable attachment types.

    Args:
        type_uti: Uniform Type Identifier.

    Returns:
        Reason string if attachment should be skipped, None if exportable.
    """
    return NON_EXPORTABLE_UTIS.get(type_uti)


def generate_manifest(
    manifest_path: Path,
    note: Note,
    exported: list[ExportedAttachment],
    skipped: list[ExportedAttachment],
) -> None:
    """Generate manifest.json for exported attachments.

    Args:
        manifest_path: Path to write manifest.json.
        note: The note being exported.
        exported: List of successfully exported attachments.
        skipped: List of skipped attachments.
    """
    # Combine exported and skipped, maintaining order
    all_attachments = []
    for att in exported:
        all_attachments.append(
            {
                "identifier": att.identifier,
                "filename": att.filename,
                "type_uti": att.type_uti,
                "exported": att.exported,
            }
        )
    for att in skipped:
        all_attachments.append(
            {
                "identifier": att.identifier,
                "filename": att.filename,
                "type_uti": att.type_uti,
                "exported": att.exported,
                "skip_reason": att.skip_reason,
            }
        )

    manifest = {
        "note_id": note.id,
        "note_identifier": note.identifier,
        "note_title": note.title,
        "exported_at": datetime.now(UTC).isoformat(),
        "attachments": all_attachments,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def export_attachments(
    conn: sqlite3.Connection,
    attachments: list[Attachment],
    output_dir: Path,
    base_name: str,
    note: Note,
) -> AttachmentExportResult:
    """Export all attachments for a note to disk.

    Creates {base_name}_attachments/ directory containing:
    - Binary files for exportable attachments
    - manifest.json listing all attachments

    Args:
        conn: Database connection.
        attachments: List of attachments from note content.
        output_dir: Parent directory for output.
        base_name: Base name for attachments directory.
        note: The note being exported.

    Returns:
        AttachmentExportResult with lists of exported/skipped attachments.
    """
    if not attachments:
        return AttachmentExportResult(
            exported=[],
            skipped=[],
            manifest_path=None,
            attachments_dir=None,
        )

    exported: list[ExportedAttachment] = []
    skipped: list[ExportedAttachment] = []
    used_names: set[str] = set()

    # Create attachments directory
    attachments_dir = output_dir / f"{base_name}_attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    for att in attachments:
        # Check if this type is exportable
        skip_reason = get_skip_reason(att.type_uti)
        if skip_reason:
            skipped.append(
                ExportedAttachment(
                    identifier=att.identifier,
                    filename=None,
                    type_uti=att.type_uti,
                    exported=False,
                    skip_reason=skip_reason,
                )
            )
            continue

        # Fetch binary data
        data = db.get_attachment_data(conn, att.identifier)
        if data is None:
            skipped.append(
                ExportedAttachment(
                    identifier=att.identifier,
                    filename=None,
                    type_uti=att.type_uti,
                    exported=False,
                    skip_reason="No binary data in database",
                )
            )
            continue

        binary_data, type_uti, db_title = data

        # Determine filename
        title = att.title or db_title
        if title:
            filename = sanitize_filename(title)
        else:
            # Generate from UTI
            ext = uti_to_extension(type_uti)
            filename = f"attachment{ext}"

        # Ensure extension
        if "." not in filename:
            filename += uti_to_extension(type_uti)

        # Make unique
        filename = make_unique_filename(filename, att.identifier, used_names)

        # Write file
        file_path = attachments_dir / filename
        file_path.write_bytes(binary_data)

        exported.append(
            ExportedAttachment(
                identifier=att.identifier,
                filename=filename,
                type_uti=att.type_uti,
                exported=True,
                skip_reason=None,
            )
        )

    # Generate manifest
    manifest_path = attachments_dir / "manifest.json"
    generate_manifest(manifest_path, note, exported, skipped)

    return AttachmentExportResult(
        exported=exported,
        skipped=skipped,
        manifest_path=manifest_path,
        attachments_dir=attachments_dir,
    )


def create_archive(
    base_path: Path,
    note_file: Path,
    attachments_dir: Path | None,
) -> Path:
    """Create 7zip archive containing note and attachments.

    After archiving, cleans up the original files.

    Args:
        base_path: Base path for archive (without extension).
        note_file: Path to the exported note file.
        attachments_dir: Path to attachments directory, or None if no attachments.

    Returns:
        Path to created .7z archive.
    """
    archive_path = base_path.with_suffix(".7z")

    with py7zr.SevenZipFile(archive_path, "w") as archive:
        # Add note file at root
        archive.write(note_file, note_file.name)

        # Add attachments directory if present
        if attachments_dir and attachments_dir.exists():
            for file in attachments_dir.rglob("*"):
                if file.is_file():
                    arcname = f"{attachments_dir.name}/{file.relative_to(attachments_dir)}"
                    archive.write(file, arcname)

    # Clean up temporary files after archiving
    note_file.unlink()
    if attachments_dir and attachments_dir.exists():
        shutil.rmtree(attachments_dir)

    return archive_path
