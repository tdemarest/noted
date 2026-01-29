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
