"""Attachment export functionality for Apple Notes.

Handles extracting attachments from notes and exporting them to disk,
with optional 7zip compression.
"""

from dataclasses import dataclass
from pathlib import Path


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
