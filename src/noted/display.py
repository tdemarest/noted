"""Terminal display formatting using Rich."""

import html
import json
import re

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table as RichTable
from rich.text import Text
from rich.tree import Tree

from noted.db import FolderInfo
from noted.models import (
    Attachment,
    DatabaseStats,
    FormattedRun,
    Note,
    NoteContent,
    NoteSummary,
    ParagraphType,
    SearchResult,
    Table,
    TextAlignment,
    TextStyle,
)

console = Console()


def display_notes_table(notes: list[Note], search: str | None = None) -> None:
    """Render notes as a Rich table.

    Args:
        notes: List of notes to display.
        search: Optional search term to highlight in results.
    """
    if not notes:
        if search:
            console.print(f"[yellow]No notes matching '{search}'.[/yellow]")
        else:
            console.print("[yellow]No notes found.[/yellow]")
        return

    title = f"Notes matching '{search}'" if search else "Notes"
    table = RichTable(title=title, show_lines=False)
    table.add_column("ID", style="dim", width=6)
    table.add_column("Title", style="bold")
    table.add_column("Folder", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Modified", style="green")

    for note in notes:
        created_str = note.created.strftime("%Y-%m-%d %H:%M") if note.created else "-"
        modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"

        # Highlight search matches in title and folder
        if search:
            title_display = _highlight_match(note.title, search)
            folder_display = _highlight_match(note.folder or "(No Folder)", search)
        else:
            title_display = Text(note.title)
            folder_display = Text(note.folder or "(No Folder)", style="cyan")

        table.add_row(
            str(note.id),
            title_display,
            folder_display,
            created_str,
            modified_str,
        )

    console.print(table)
    if search:
        console.print(f"\n[dim]Found: {len(notes)} notes matching '{search}'[/dim]")
    else:
        console.print(f"\n[dim]Total: {len(notes)} notes[/dim]")


def _highlight_match(text: str, search: str) -> Text:
    """Highlight search term matches in text using Rich Text.

    Performs case-insensitive matching and highlights all occurrences.

    Args:
        text: The text to search within.
        search: The search term to highlight.

    Returns:
        Rich Text object with highlighted matches.
    """
    result = Text()
    search_lower = search.lower()
    text_lower = text.lower()

    pos = 0
    while pos < len(text):
        match_pos = text_lower.find(search_lower, pos)
        if match_pos == -1:
            # No more matches, append rest of text
            result.append(text[pos:])
            break
        else:
            # Append text before match
            if match_pos > pos:
                result.append(text[pos:match_pos])
            # Append highlighted match (preserve original case)
            result.append(
                text[match_pos : match_pos + len(search)],
                style="bold yellow on red",
            )
            pos = match_pos + len(search)

    return result


# Tree view icons
TREE_ICONS = {
    "folder": "📁",
    "folder_smart": "🔎",
    "folder_system": "⚙️",
    "trash": "🗑️",
    "note": "📄",
    "locked": "🔒",
    "checklist_complete": "✅",
    "checklist_incomplete": "🔲",
}

# Attachment type icons for tree view
ATTACHMENT_ICONS = {
    "Images": "📷",
    "PDFs": "📄",
    "Videos": "🎬",
    "Office": "📊",
    "Links": "🔗",
    "Generic": "📎",
}


def _categorize_attachment(uti: str) -> str:
    """Categorize a UTI into a display group.

    Args:
        uti: Uniform Type Identifier string.

    Returns:
        Category name for the attachment type.
    """
    group = _UTI_TO_GROUP.get(uti)
    if group in ATTACHMENT_ICONS:
        return group
    return "Generic"


# UTI to human-readable type name for attachment markers
_UTI_TYPE_NAMES: dict[str, str] = {
    "public.jpeg": "Image",
    "public.png": "Image",
    "public.heic": "Image",
    "public.gif": "Image",
    "public.tiff": "Image",
    "com.compuserve.gif": "Image",
    "com.adobe.pdf": "PDF",
    "public.pdf": "PDF",
    "com.apple.drawing": "Drawing",
    "com.apple.drawing.2": "Drawing",
    "public.url": "Link",
    "com.apple.mapkit.map-item": "Map",
    "public.vcard": "Contact",
    "com.apple.notes.table": "Table",
    "com.apple.notes.gallery": "Gallery",
}


def _attachment_type_name(uti: str) -> str:
    """Get human-readable type name for a UTI.

    Args:
        uti: Uniform Type Identifier string.

    Returns:
        Human-readable type name (e.g., 'Image', 'PDF').
    """
    return _UTI_TYPE_NAMES.get(uti, "Attachment")


def _format_attachment_icons(type_counts: dict[str, int]) -> str:
    """Format attachment types as consolidated icons.

    Args:
        type_counts: Mapping of UTI type to count.

    Returns:
        Formatted string like '📷×3 📊' or empty string if no attachments.
    """
    if not type_counts:
        return ""

    # Consolidate by category
    category_counts: dict[str, int] = {}
    for uti, count in type_counts.items():
        category = _categorize_attachment(uti)
        category_counts[category] = category_counts.get(category, 0) + count

    # Build icon string
    parts = []
    for category, count in sorted(category_counts.items()):
        icon = ATTACHMENT_ICONS.get(category, "📎")
        if count > 1:
            parts.append(f"{icon}×{count}")
        else:
            parts.append(icon)

    return " ".join(parts)


def display_notes_tree(
    folders: list[FolderInfo],
    notes: list[Note],
    attachment_types: dict[int, dict[str, int]] | None = None,
    verbose: bool = False,
) -> None:
    """Render notes organized by folder hierarchy using Rich Tree.

    Args:
        folders: List of FolderInfo from db.get_folders().
        notes: List of Note objects (with checklist fields).
        attachment_types: Optional mapping of note_id to UTI type counts.
        verbose: If True, show individual notes with attachments.
    """
    if not folders:
        console.print("[yellow]No folders found.[/yellow]")
        return

    # Calculate total notes
    total_count = sum(f.note_count for f in folders)

    # Create root tree
    root = Tree(f"[bold]{TREE_ICONS['folder']} Notes[/bold] [dim]({total_count})[/dim]")

    # Build folder hierarchy from paths
    # folders are already sorted by path from get_folders()
    folder_nodes: dict[str, Tree] = {}

    for folder in folders:
        path = folder.path
        parts = path.split("/")

        # Navigate/create path
        current_node = root
        current_path = ""

        for i, part in enumerate(parts):
            current_path = "/".join(parts[: i + 1])

            if current_path not in folder_nodes:
                # This is the folder we're adding
                if current_path == path:
                    # Choose icon based on folder type
                    if folder.folder_type == 2:
                        icon = TREE_ICONS["folder_smart"]
                    elif folder.folder_type == 1:
                        icon = TREE_ICONS["folder_system"]
                    else:
                        icon = TREE_ICONS["folder"]
                    # This is the actual folder entry
                    label = f"{icon} {part} [dim]({folder.note_count})[/dim]"
                else:
                    # Intermediate folder not in our list, show without count
                    icon = TREE_ICONS["folder"]
                    label = f"{icon} {part}"

                new_node = current_node.add(label)
                folder_nodes[current_path] = new_node
                current_node = new_node
            else:
                current_node = folder_nodes[current_path]

    # If verbose, add notes under their folders
    if verbose and notes:
        # Build lookup from folder name to full path (for notes with immediate folder name)
        folder_name_to_paths: dict[str, list[str]] = {}
        for folder in folders:
            name = folder.path.split("/")[-1]  # Get immediate folder name
            if name not in folder_name_to_paths:
                folder_name_to_paths[name] = []
            folder_name_to_paths[name].append(folder.path)

        # Group notes by folder path
        notes_by_folder: dict[str, list[Note]] = {}
        for note in notes:
            folder_name = note.folder
            if folder_name is None:
                continue

            # Find matching folder path(s) - if multiple, use first match
            matching_paths = folder_name_to_paths.get(folder_name, [])
            if matching_paths:
                folder_path = matching_paths[0]
                if folder_path not in notes_by_folder:
                    notes_by_folder[folder_path] = []
                notes_by_folder[folder_path].append(note)

        # Add notes to each folder node
        for folder_path, folder_notes in notes_by_folder.items():
            if folder_path in folder_nodes:
                node = folder_nodes[folder_path]
            else:
                # Notes without a folder or unmatched folder
                continue

            for note in folder_notes:
                # Build note label
                label_parts = [f"{TREE_ICONS['note']} {note.title}"]

                # Add lock indicator (takes precedence over other indicators)
                if note.is_locked:
                    label_parts.append(f" {TREE_ICONS['locked']}")
                elif note.has_checklist:
                    # Add checklist indicator
                    if note.checklist_complete:
                        label_parts.append(f" {TREE_ICONS['checklist_complete']}")
                    else:
                        label_parts.append(f" {TREE_ICONS['checklist_incomplete']}")

                # Add attachment icons
                if attachment_types and note.id in attachment_types:
                    att_icons = _format_attachment_icons(attachment_types[note.id])
                    if att_icons:
                        label_parts.append(f" {att_icons}")

                node.add("".join(label_parts))

    console.print(root)


def _format_snippet(snippet: str) -> Text:
    """Format an FTS5 snippet with highlighted matches.

    FTS5 uses <<< and >>> markers around matched terms.
    This converts them to Rich Text with highlighting.

    Args:
        snippet: FTS5 snippet with <<< >>> markers.

    Returns:
        Rich Text object with highlighted matches.
    """
    result = Text()

    pos = 0
    while pos < len(snippet):
        start = snippet.find("<<<", pos)
        if start == -1:
            # No more markers, append rest
            result.append(snippet[pos:])
            break

        # Append text before marker
        if start > pos:
            result.append(snippet[pos:start])

        # Find end marker
        end = snippet.find(">>>", start)
        if end == -1:
            # Malformed, append rest as-is
            result.append(snippet[pos:])
            break

        # Extract and highlight matched term
        matched = snippet[start + 3 : end]
        result.append(matched, style="bold yellow on red")
        pos = end + 3

    return result


def display_search_results(results: list[SearchResult], query: str) -> None:
    """Display FTS5 search results as a Rich table.

    Shows note metadata with content snippets highlighting matches.

    Args:
        results: List of SearchResult objects from search_notes().
        query: The search query (for display in title).
    """
    if not results:
        console.print(f"[yellow]No notes matching '{query}' in content.[/yellow]")
        return

    table = RichTable(title=f"Deep search: '{query}'", show_lines=True)
    table.add_column("ID", style="dim", width=6)
    table.add_column("Title", style="bold", width=30)
    table.add_column("Folder", style="cyan", width=20)
    table.add_column("Match Context", width=50)

    for result in results:
        note = result.note

        # Format snippet with highlighting
        snippet_text = _format_snippet(result.snippet)

        table.add_row(
            str(note.id),
            note.title,
            note.folder or "(No Folder)",
            snippet_text,
        )

    console.print(table)
    console.print(f"\n[dim]Found: {len(results)} notes matching '{query}'[/dim]")


def display_count(summary: NoteSummary) -> None:
    """Display note counts.

    Args:
        summary: NoteSummary with counts.
    """
    console.print(f"[bold]Total notes:[/bold] {summary.total_count}")

    if summary.folder_counts:
        console.print("\n[bold]By folder:[/bold]")
        table = RichTable(show_header=True, header_style="bold")
        table.add_column("Folder")
        table.add_column("Count", justify="right")

        for folder, count in summary.folder_counts.items():
            table.add_row(folder, str(count))

        console.print(table)


# Attachment type groupings for cleaner display
_ATTACHMENT_GROUPS: dict[str, list[str]] = {
    "Images": [
        "public.jpeg",
        "public.png",
        "public.heic",
        "public.gif",
        "public.tiff",
        "com.compuserve.gif",
        "org.webmproject.webp",
        "public.svg-image",
        "public.image",
    ],
    "PDFs": [
        "com.adobe.pdf",
        "public.pdf",
        "com.apple.paper.doc.pdf",
    ],
    "Videos": [
        "com.apple.quicktime-movie",
        "public.mpeg-4",
        "public.movie",
    ],
    "Office": [
        "org.openxmlformats.spreadsheetml.sheet",
        "org.openxmlformats.wordprocessingml.document",
        "org.openxmlformats.presentationml.presentation",
        "com.microsoft.excel.xls",
        "com.microsoft.word.doc",
    ],
    "Tables": [
        "com.apple.notes.table",
    ],
    "Links": [
        "public.url",
    ],
    "Emails": [
        "com.apple.mail.email",
    ],
    "Drawings": [
        "com.apple.drawing",
        "com.apple.drawing.2",
    ],
}

# Build reverse lookup: UTI -> group name
_UTI_TO_GROUP: dict[str, str] = {}
for group_name, utis in _ATTACHMENT_GROUPS.items():
    for uti in utis:
        _UTI_TO_GROUP[uti] = group_name

# Subtype display names for breakdown
_IMAGE_SUBTYPES: dict[str, str] = {
    "public.jpeg": "JPEG",
    "public.png": "PNG",
    "public.heic": "HEIC",
    "public.gif": "GIF",
    "com.compuserve.gif": "GIF",
    "public.tiff": "TIFF",
    "org.webmproject.webp": "WebP",
    "public.svg-image": "SVG",
}


def display_stats(stats: DatabaseStats) -> None:
    """Display comprehensive database statistics with rich formatting.

    Args:
        stats: DatabaseStats with all statistics.
    """
    console.print("[bold cyan]Database Statistics[/bold cyan]")
    console.print("━" * 56)

    # Cache info section
    console.print("\n[bold]Cache[/bold]")
    if stats.database_size_bytes > 0:
        console.print(f"  {'Database size:':<20} {_format_file_size(stats.database_size_bytes)}")
    if stats.cache_modified:
        modified_str = stats.cache_modified.strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"  {'Last updated:':<20} {modified_str}")
    if stats.fts_index_size_bytes > 0:
        fresh_indicator = "[green]✓[/green]" if stats.fts_index_fresh else "[yellow]stale[/yellow]"
        console.print(
            f"  {'FTS index:':<20} {_format_file_size(stats.fts_index_size_bytes)} "
            f"({stats.fts_indexed_notes:,} notes) {fresh_indicator}"
        )
        if stats.fts_index_built_at:
            # Parse ISO timestamp and format nicely
            try:
                from datetime import datetime

                built_dt = datetime.fromisoformat(stats.fts_index_built_at)
                built_str = built_dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                built_str = stats.fts_index_built_at
            console.print(f"  {'Index built:':<20} {built_str}")
    elif stats.fts_indexed_notes == 0:
        console.print(f"  {'FTS index:':<20} [dim]not built[/dim]")

    # Notes section - use consistent label width and right-aligned numbers
    console.print("\n[bold]Notes[/bold]")
    console.print(f"  {'Total:':<20} {stats.total_notes:>6,}")
    if stats.pinned_notes > 0:
        console.print(f"  {'Pinned:':<20} {stats.pinned_notes:>6,}")
    if stats.locked_notes > 0:
        console.print(f"  {'Locked:':<20} {stats.locked_notes:>6,}")
    if stats.notes_with_checklists > 0:
        incomplete_info = ""
        if stats.notes_with_incomplete_checklists > 0:
            incomplete_info = f" ({stats.notes_with_incomplete_checklists} incomplete)"
        count_str = f"{stats.notes_with_checklists:>6,}"
        console.print(f"  {'With checklists:':<20} {count_str}{incomplete_info}")
    if stats.deleted_notes > 0:
        console.print(f"  {'Recently deleted:':<20} {stats.deleted_notes:>6,}")

    # Attachments section
    if stats.total_attachments > 0:
        console.print(f"\n[bold]Attachments[/bold] ({stats.total_attachments:,} total)")

        # Group attachments by category
        grouped: dict[str, int] = {}
        image_subtypes: dict[str, int] = {}
        other_count = 0

        for uti, count in stats.attachment_type_counts.items():
            group = _UTI_TO_GROUP.get(uti)
            if group:
                grouped[group] = grouped.get(group, 0) + count
                # Track image subtypes for detailed breakdown
                if group == "Images" and uti in _IMAGE_SUBTYPES:
                    subtype = _IMAGE_SUBTYPES[uti]
                    image_subtypes[subtype] = image_subtypes.get(subtype, 0) + count
            else:
                other_count += count

        # Display groups in a consistent order
        display_order = [
            "PDFs", "Images", "Tables", "Links", "Office", "Emails", "Videos", "Drawings"
        ]
        for group in display_order:
            if group in grouped:
                count = grouped[group]
                label = f"{group}:"
                # Special handling for images with subtype breakdown
                if group == "Images" and image_subtypes:
                    # Sort subtypes by count
                    sorted_subtypes = sorted(image_subtypes.items(), key=lambda x: -x[1])
                    subtype_str = ", ".join(f"{name}: {c}" for name, c in sorted_subtypes[:4])
                    if len(sorted_subtypes) > 4:
                        subtype_str += ", ..."
                    console.print(f"  {label:<20} {count:>6,}  [dim]({subtype_str})[/dim]")
                else:
                    console.print(f"  {label:<20} {count:>6,}")

        if other_count > 0:
            console.print(f"  {'Other:':<20} {other_count:>6,}")

        if stats.attachments_with_location > 0:
            console.print(f"\n  {'With location data:':<20} {stats.attachments_with_location:>6,}")

    # Folders section (if requested)
    if stats.folder_counts:
        folder_count = len(stats.folder_counts)
        console.print(f"\n[bold]Folders[/bold] ({folder_count} total)")
        table = RichTable(show_header=True, header_style="bold", box=box.SIMPLE)
        table.add_column("Folder")
        table.add_column("Notes", justify="right")

        for folder, count in stats.folder_counts.items():
            table.add_row(folder, str(count))

        console.print(table)


def stats_to_json(stats: DatabaseStats) -> str:
    """Convert DatabaseStats to JSON string.

    Args:
        stats: DatabaseStats with all statistics.

    Returns:
        JSON-formatted string.
    """
    data: dict[str, object] = {
        "cache": {
            "database_size_bytes": stats.database_size_bytes,
            "modified": stats.cache_modified.isoformat() if stats.cache_modified else None,
            "fts_index_size_bytes": stats.fts_index_size_bytes,
            "fts_index_built_at": stats.fts_index_built_at,
            "fts_index_fresh": stats.fts_index_fresh,
            "fts_indexed_notes": stats.fts_indexed_notes,
        },
        "notes": {
            "total": stats.total_notes,
            "pinned": stats.pinned_notes,
            "locked": stats.locked_notes,
            "deleted": stats.deleted_notes,
            "with_checklists": stats.notes_with_checklists,
            "with_incomplete_checklists": stats.notes_with_incomplete_checklists,
        },
        "attachments": {
            "total": stats.total_attachments,
            "with_location": stats.attachments_with_location,
            "by_type": stats.attachment_type_counts,
        },
    }
    if stats.folder_counts:
        data["folders"] = stats.folder_counts
    return json.dumps(data, indent=2)


def display_error(message: str) -> None:
    """Display error message.

    Args:
        message: Error message to display.
    """
    console.print(f"[bold red]Error:[/bold red] {message}")


def display_success(message: str) -> None:
    """Display success message.

    Args:
        message: Success message to display.
    """
    console.print(f"[bold green]Success:[/bold green] {message}")


def display_warning(message: str) -> None:
    """Display warning message.

    Args:
        message: Warning message to display.
    """
    console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def display_export_success(folder: str | None, title: str, attachment_count: int = 0) -> None:
    """Display verbose export success message with rich formatting.

    Args:
        folder: Note folder name (or None for no folder).
        title: Note title.
        attachment_count: Number of attachments exported.
    """
    folder_display = folder or "(No Folder)"
    att_info = f" [dim]({attachment_count} attachments)[/dim]" if attachment_count else ""
    console.print(
        f"  [bold green]✓[/bold green] [cyan]{folder_display}[/cyan]/"
        f"[bold]{title}[/bold]{att_info}"
    )


def display_export_locked(folder: str | None, title: str) -> None:
    """Display verbose export locked note message with rich formatting.

    Args:
        folder: Note folder name (or None for no folder).
        title: Note title.
    """
    folder_display = folder or "(No Folder)"
    console.print(
        f"  [bold yellow]⚠[/bold yellow] [cyan]{folder_display}[/cyan]/[bold]{title}[/bold] "
        f"[yellow](locked)[/yellow]"
    )


def display_export_failed(folder: str | None, title: str, error: str | None) -> None:
    """Display verbose export failure message with rich formatting.

    Args:
        folder: Note folder name (or None for no folder).
        title: Note title.
        error: Error message describing the failure.
    """
    folder_display = folder or "(No Folder)"
    error_msg = error or "Unknown error"
    console.print(
        f"  [bold red]✗[/bold red] [cyan]{folder_display}[/cyan]/[bold]{title}[/bold] "
        f"[red](failed: {error_msg})[/red]"
    )


def display_export_issues_summary(
    locked_notes: list[tuple[str | None, str]],
    failed_notes: list[tuple[str | None, str, str | None]],
) -> None:
    """Display summary of locked and failed notes after export.

    Args:
        locked_notes: List of (folder, title) tuples for locked notes.
        failed_notes: List of (folder, title, error) tuples for failed notes.
    """
    if locked_notes:
        console.print()
        console.print("[bold yellow]Locked notes:[/bold yellow]")
        for folder, title in locked_notes:
            folder_display = folder or "(No Folder)"
            console.print(
                f"  [yellow]⚠[/yellow] [cyan]{folder_display}[/cyan]/[bold]{title}[/bold]"
            )

    if failed_notes:
        console.print()
        console.print("[bold red]Failed notes:[/bold red]")
        for folder, title, error in failed_notes:
            folder_display = folder or "(No Folder)"
            error_msg = error or "Unknown error"
            console.print(
                f"  [red]✗[/red] [cyan]{folder_display}[/cyan]/[bold]{title}[/bold] "
                f"[dim]({error_msg})[/dim]"
            )


def _format_file_size(size_bytes: int | float) -> str:
    """Format a file size in bytes to human-readable string.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted string like "1.5 MB" or "256 KB".
    """
    if size_bytes == 0:
        return "0 B"

    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(size) < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def display_debug_note_info(
    note: Note,
    attachment_stats: dict[str, int | float] | None = None,
) -> None:
    """Display debug information about a note.

    Shows row ID, UUID, title, folder, timestamps, and attachment stats
    in a formatted panel.

    Args:
        note: Note object with metadata.
        attachment_stats: Optional dict with 'count' and 'total_size' keys.
    """
    from rich.table import Table as RichTable

    table = RichTable(
        title="[bold cyan]Debug: Note Info[/bold cyan]",
        show_header=False,
        box=box.SIMPLE,
        title_justify="left",
        padding=(0, 1),
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", style="bold")

    table.add_row("Row ID", str(note.id))
    table.add_row("UUID", note.identifier)
    table.add_row("Title", note.title)
    table.add_row("Folder", note.folder or "(No Folder)")
    if note.created:
        table.add_row("Created", note.created.strftime("%Y-%m-%d %H:%M:%S"))
    if note.modified:
        table.add_row("Modified", note.modified.strftime("%Y-%m-%d %H:%M:%S"))

    # Add attachment stats if provided
    if attachment_stats is not None:
        count = attachment_stats.get("count", 0)
        total_size = attachment_stats.get("total_size", 0)
        table.add_row("Attachments", str(count))
        if count > 0:
            table.add_row("Attachment Size", _format_file_size(total_size))

    console.print(table)
    console.print()


def display_note_view(note: Note, content: NoteContent) -> None:
    """Display a note's full content.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
    """
    # Format metadata line
    folder_str = note.folder or "(No Folder)"
    modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"
    subtitle = f"Folder: {folder_str}  |  Modified: {modified_str}"

    # Create header panel
    panel = Panel(
        Text(subtitle, style="dim"),
        title=f"[bold]{note.title}[/bold]",
        title_align="left",
        border_style="blue",
    )
    console.print(panel)
    console.print()

    # Build attachment lookup for inline rendering
    table_lookup: dict[str, Table] = {}
    attachments_list: list[Attachment] = content.attachments or []
    for att in attachments_list:
        if att.type_uti == "com.apple.notes.table" and att.table is not None:
            table_lookup[att.identifier] = att.table

    # Use formatted rendering if available
    if content.formatted_runs:
        _render_formatted_content(content.formatted_runs, table_lookup, attachments_list)
    elif content.text:
        _render_text_with_tables(content.text, table_lookup)
    else:
        console.print("[dim]No content[/dim]")


def _render_formatted_content(
    runs: list[FormattedRun],
    table_lookup: dict[str, Table],
    attachments_list: list[Attachment],
) -> None:
    """Render formatted content with rich styling.

    Args:
        runs: List of formatted text runs.
        table_lookup: Mapping of table identifier to parsed Table.
        attachments_list: Ordered list of all attachments in the note.
    """
    # Object replacement character used by Apple Notes for attachments
    object_replacement_char = "\ufffc"
    attachment_index = 0

    # Track numbered list counter
    numbered_list_count = 0
    last_list_type: int | None = None

    # First pass: collect runs into lines/paragraphs for better rendering
    # Group consecutive runs by paragraph type for lists and special blocks
    i = 0
    while i < len(runs):
        run = runs[i]
        text = run.text
        para = run.paragraph_style
        style = run.text_style
        para_type = para.paragraph_type if para else None

        # Handle attachment placeholders (U+FFFC) - tables and other attachments
        if object_replacement_char in text:
            if attachment_index < len(attachments_list):
                att = attachments_list[attachment_index]
                attachment_index += 1
                if att.identifier in table_lookup:
                    # Render table inline
                    rich_table = table_to_rich(table_lookup[att.identifier])
                    console.print(rich_table)
                elif att.type_uti == "com.apple.notes.table":
                    console.print("[Table]", end="")
                elif att.title:
                    # Show filename for non-table attachments
                    console.print(f"[{att.title}]", end="")
                else:
                    console.print("[Attachment]", end="")
            else:
                console.print("[Attachment]", end="")
            i += 1
            continue

        # Handle code blocks - collect all consecutive code runs
        if para_type == ParagraphType.MONOSPACE:
            code_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                if next_para and next_para.paragraph_type == ParagraphType.MONOSPACE:
                    code_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            console.print(Syntax(code_text.rstrip(), "python", theme="monokai", line_numbers=False))
            continue

        # Handle block quotes - collect all consecutive quote runs
        if para and para.is_quote:
            quote_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                if next_para and next_para.is_quote:
                    quote_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            quote_panel = Panel(
                Text(quote_text.strip(), style="italic"),
                border_style="dim",
                padding=(0, 2),
            )
            console.print(quote_panel)
            continue

        # Handle lists - collect runs until newline to form complete item
        if para_type in (
            ParagraphType.BULLET_LIST,
            ParagraphType.DASHED_LIST,
            ParagraphType.NUMBERED_LIST,
            ParagraphType.CHECKLIST,
        ):
            # Collect all runs for this list item (until newline)
            item_runs = [run]
            j = i + 1
            while j < len(runs) and "\n" not in runs[j - 1].text:
                next_para = runs[j].paragraph_style
                next_type = next_para.paragraph_type if next_para else None
                if next_type == para_type:
                    item_runs.append(runs[j])
                    j += 1
                else:
                    break
            i = j

            # Build the item text with styling and exposed link URLs
            item_text = Text()
            for r in item_runs:
                char_style = _get_char_style(r.text_style, r.link)
                item_text.append(r.text, style=char_style or None)
                if r.link:
                    item_text.append(f" ({r.link})", style="dim")

            # Determine indent and prefix
            indent = "  " * (para.indent_level if para else 0)

            if para_type == ParagraphType.BULLET_LIST:
                prefix = f"{indent}• "
                console.print(prefix, end="", style="cyan")
                last_list_type = para_type
            elif para_type == ParagraphType.DASHED_LIST:
                prefix = f"{indent}– "
                console.print(prefix, end="", style="cyan")
                last_list_type = para_type
            elif para_type == ParagraphType.NUMBERED_LIST:
                # Track numbered list count
                if last_list_type != ParagraphType.NUMBERED_LIST:
                    numbered_list_count = 0
                numbered_list_count += 1
                prefix = f"{indent}{numbered_list_count}. "
                console.print(prefix, end="", style="cyan")
                last_list_type = para_type
            elif para_type == ParagraphType.CHECKLIST:
                # Check if paragraph is marked as checked
                is_checked = para.is_checked if para else False
                checkbox = "☑" if is_checked else "☐"
                check_style = "green" if is_checked else "yellow"
                console.print(f"{indent}{checkbox} ", end="", style=check_style)
                if is_checked:
                    item_text.stylize("dim strike")
                last_list_type = para_type

            # Print item text (remove trailing newline, we'll add it)
            item_str = str(item_text).rstrip("\n")
            item_text = Text(item_str)
            for r in item_runs:
                char_style = _get_char_style(r.text_style, r.link)
                if char_style:
                    # Re-apply styling after stripping
                    pass
            console.print(item_text)
            continue

        # Handle headings
        if para_type == ParagraphType.TITLE:
            console.print(text, style="bold magenta", end="")
            i += 1
            continue

        if para_type == ParagraphType.HEADING:
            console.print(text, style="bold cyan", end="")
            i += 1
            continue

        if para_type == ParagraphType.SUBHEADING:
            console.print(text, style="bold blue", end="")
            i += 1
            continue

        # Regular text with character styling
        char_style = _get_char_style(style, run.link)

        # Build text with link URL exposed if present
        display_text = Text()
        display_text.append(text, style=char_style or None)
        if run.link:
            display_text.append(f" ({run.link})", style="dim")

        # Handle alignment
        if para and para.alignment == TextAlignment.CENTER:
            console.print(display_text, justify="center", end="")
        elif para and para.alignment == TextAlignment.RIGHT:
            console.print(display_text, justify="right", end="")
        else:
            console.print(display_text, end="")

        i += 1


def _get_char_style(style: TextStyle | None, link: str | None) -> str:
    """Build Rich style string from TextStyle.

    Args:
        style: Text styling info.
        link: URL if this is a hyperlink.

    Returns:
        Rich style string like "bold italic underline".
    """
    parts = []
    if style:
        if style.bold:
            parts.append("bold")
        if style.italic:
            parts.append("italic")
        if style.underline:
            parts.append("underline")
        if style.strikethrough:
            parts.append("strike")
        if style.highlight:
            parts.append("on yellow")
    if link:
        parts.append("blue underline")
    return " ".join(parts)


def _render_text_with_tables(text: str, table_lookup: dict[str, Table]) -> None:
    """Render text, replacing [Table:id] markers with actual tables.

    Args:
        text: Note text with [Table:identifier] markers.
        table_lookup: Mapping of identifier to parsed Table.
    """
    # Pattern matches [Table:uuid-here]
    pattern = r"\[Table:([^\]]+)\]"

    last_end = 0
    for match in re.finditer(pattern, text):
        # Print text before this marker
        before = text[last_end : match.start()]
        if before:
            console.print(before, end="")

        # Render the table
        identifier = match.group(1)
        if identifier in table_lookup:
            table = table_lookup[identifier]
            rich_table = table_to_rich(table)
            console.print()
            console.print(rich_table)
        else:
            # Table not parsed, show placeholder
            console.print("[Table]", end="")

        last_end = match.end()

    # Print remaining text
    remaining = text[last_end:]
    if remaining:
        console.print(remaining)


def table_to_rich(table: Table) -> RichTable:
    """Convert Table data to Rich Table for terminal display.

    Args:
        table: Parsed table data.

    Returns:
        Rich Table object ready for printing.
    """
    rich_table = RichTable(box=box.SIMPLE, show_header=False)

    # Add columns
    for _ in range(table.columns):
        rich_table.add_column()

    # Add rows
    for row in range(table.rows):
        row_data = [table.get_cell(row, col) for col in range(table.columns)]
        rich_table.add_row(*row_data)

    return rich_table


def table_to_markdown(table: Table) -> str:
    """Convert Table data to markdown string.

    Args:
        table: Parsed table data.

    Returns:
        Markdown-formatted table string.
    """
    if table.rows == 0 or table.columns == 0:
        return ""

    lines = []

    # Header row (first row of data)
    header = [table.get_cell(0, col) or " " for col in range(table.columns)]
    lines.append("| " + " | ".join(header) + " |")

    # Separator
    lines.append("| " + " | ".join(["---"] * table.columns) + " |")

    # Data rows
    for row in range(1, table.rows):
        cells = [table.get_cell(row, col) or " " for col in range(table.columns)]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def get_note_markdown(note: Note, content: NoteContent) -> str:
    """Get a note as raw markdown text.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.

    Returns:
        Markdown-formatted string.
    """
    # Build attachment lookup for inline rendering
    table_lookup: dict[str, Table] = {}
    if content.attachments:
        for att in content.attachments:
            if att.table is not None:
                table_lookup[att.identifier] = att.table

    # Convert to markdown (skip_title=True since we add our own)
    md_text = note_to_markdown(content, table_lookup, skip_first_title=True)

    # Add title as H1
    return f"# {note.title}\n\n{md_text}"


def display_note_markdown(note: Note, content: NoteContent) -> None:
    """Output a note as raw markdown text.

    Outputs plain markdown that can be piped to tools like glow,
    copied to Notion, or saved to a .md file.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
    """
    print(get_note_markdown(note, content))


def note_to_markdown(
    content: NoteContent,
    table_lookup: dict[str, Table],
    skip_first_title: bool = False,
) -> str:
    """Convert note content to markdown string.

    Args:
        content: Parsed note content with formatted runs.
        table_lookup: Mapping of table identifier to parsed Table.
        skip_first_title: If True, skip the first TITLE paragraph (to avoid
            duplicating the note title we add separately).

    Returns:
        Markdown-formatted string.
    """
    if not content.formatted_runs:
        return content.text or ""

    skipped_first_title = False

    # Object replacement character used by Apple Notes for attachments
    object_replacement_char = "\ufffc"

    # Build ordered list of all attachments for matching U+FFFC occurrences
    all_attachments = content.attachments or []
    attachment_index = 0

    lines: list[str] = []
    current_line = ""

    # Track list state
    numbered_list_count = 0
    last_list_type: int | None = None

    i = 0
    runs = content.formatted_runs
    while i < len(runs):
        run = runs[i]
        text = run.text

        # Handle attachment placeholders (U+FFFC)
        if object_replacement_char in text:
            if current_line:
                lines.append(current_line)
                current_line = ""
            # Look up attachment by order
            if attachment_index < len(all_attachments):
                att = all_attachments[attachment_index]
                attachment_index += 1
                if att.type_uti == "com.apple.notes.table":
                    if att.identifier in table_lookup:
                        lines.append(table_to_markdown(table_lookup[att.identifier]))
                    else:
                        lines.append("[Table]")
                else:
                    # Output marker with type and title for linking
                    type_name = _attachment_type_name(att.type_uti)
                    if att.title:
                        if type_name == "Attachment":
                            # For unknown types, just show the filename
                            lines.append(f"[{att.title}]")
                        else:
                            # For known types, show type + filename
                            lines.append(f"[{type_name}: {att.title}]")
                    else:
                        lines.append(f"[{type_name}]")
            else:
                lines.append("[Attachment]")
            i += 1
            continue
        para = run.paragraph_style
        style = run.text_style
        para_type = para.paragraph_type if para else None

        # Handle code blocks
        if para_type == ParagraphType.MONOSPACE:
            code_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                if next_para and next_para.paragraph_type == ParagraphType.MONOSPACE:
                    code_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            if current_line:
                lines.append(current_line)
                current_line = ""
            lines.append(f"```\n{code_text.rstrip()}\n```")
            continue

        # Handle block quotes
        if para and para.is_quote:
            quote_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                if next_para and next_para.is_quote:
                    quote_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            if current_line:
                lines.append(current_line)
                current_line = ""
            # Add > prefix to each line
            quote_lines = quote_text.strip().split("\n")
            lines.extend(f"> {line}" for line in quote_lines)
            continue

        # Handle lists
        if para_type in (
            ParagraphType.BULLET_LIST,
            ParagraphType.DASHED_LIST,
            ParagraphType.NUMBERED_LIST,
            ParagraphType.CHECKLIST,
        ):
            # Collect all runs for this list item
            item_runs = [run]
            j = i + 1
            while j < len(runs) and "\n" not in runs[j - 1].text:
                next_para = runs[j].paragraph_style
                next_type = next_para.paragraph_type if next_para else None
                if next_type == para_type:
                    item_runs.append(runs[j])
                    j += 1
                else:
                    break
            i = j

            # Build item text with markdown styling
            item_text = ""
            for r in item_runs:
                styled = _apply_markdown_style(r.text, r.text_style, r.link)
                item_text += styled

            # Determine indent and prefix
            indent = "  " * (para.indent_level if para else 0)

            if para_type == ParagraphType.BULLET_LIST:
                prefix = f"{indent}- "
                last_list_type = para_type
            elif para_type == ParagraphType.DASHED_LIST:
                prefix = f"{indent}- "
                last_list_type = para_type
            elif para_type == ParagraphType.NUMBERED_LIST:
                if last_list_type != ParagraphType.NUMBERED_LIST:
                    numbered_list_count = 0
                numbered_list_count += 1
                prefix = f"{indent}{numbered_list_count}. "
                last_list_type = para_type
            elif para_type == ParagraphType.CHECKLIST:
                is_checked = para.is_checked if para else False
                checkbox = "[x]" if is_checked else "[ ]"
                prefix = f"{indent}- {checkbox} "
                last_list_type = para_type
            else:
                prefix = ""

            if current_line:
                lines.append(current_line)
                current_line = ""
            lines.append(f"{prefix}{item_text.rstrip()}")
            continue

        # Handle headings - aggregate all consecutive runs of same type
        if para_type in (
            ParagraphType.TITLE,
            ParagraphType.HEADING,
            ParagraphType.SUBHEADING,
        ):
            heading_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                next_type = next_para.paragraph_type if next_para else None
                if next_type == para_type:
                    heading_text += runs[j].text
                    j += 1
                else:
                    break
            i = j

            if current_line:
                lines.append(current_line)
                current_line = ""

            heading_text = heading_text.rstrip()

            # Skip first title if requested (to avoid duplicating note title)
            if para_type == ParagraphType.TITLE and skip_first_title and not skipped_first_title:
                skipped_first_title = True
                continue

            if para_type == ParagraphType.TITLE:
                lines.append(f"# {heading_text}")
            elif para_type == ParagraphType.HEADING:
                lines.append(f"## {heading_text}")
            else:
                lines.append(f"### {heading_text}")
            continue

        # Regular text with styling - aggregate consecutive runs with same style
        has_styling = style and (style.bold or style.italic or style.strikethrough)
        # Only apply styling to non-whitespace content
        has_content = text.strip() != ""

        if has_styling and has_content and "\n" not in text:
            # Aggregate consecutive runs with matching style
            aggregated_text = text
            j = i + 1
            while j < len(runs):
                next_run = runs[j]
                next_style = next_run.text_style
                # Stop if style changes, there's a newline, or it's a link
                if not _styles_match(style, next_style):
                    break
                if "\n" in next_run.text:
                    # Include text up to the newline
                    pre_newline = next_run.text.split("\n")[0]
                    aggregated_text += pre_newline
                    break
                if next_run.link:
                    break
                aggregated_text += next_run.text
                j += 1
            i = j

            # Apply markdown to aggregated text
            styled = _apply_markdown_style(aggregated_text, style, run.link)
            current_line += styled
        else:
            # No special styling, contains newline, or whitespace-only - handle normally
            # Don't apply styling to whitespace-only runs
            effective_style = style if has_content else None
            styled = _apply_markdown_style(text, effective_style, run.link)

            # Handle newlines
            if "\n" in styled:
                parts = styled.split("\n")
                current_line += parts[0]
                lines.append(current_line)
                for part in parts[1:-1]:
                    lines.append(part)
                current_line = parts[-1]
            else:
                current_line += styled

            i += 1

    # Don't forget remaining text
    if current_line:
        lines.append(current_line)

    return "\n".join(lines)


def _styles_match(style1: TextStyle | None, style2: TextStyle | None) -> bool:
    """Check if two text styles are equivalent for markdown purposes.

    Args:
        style1: First text style.
        style2: Second text style.

    Returns:
        True if styles have the same bold/italic/strikethrough/underline values.
    """
    if style1 is None and style2 is None:
        return True
    if style1 is None or style2 is None:
        return False
    return (
        style1.bold == style2.bold
        and style1.italic == style2.italic
        and style1.strikethrough == style2.strikethrough
        and style1.underline == style2.underline
    )


def _apply_markdown_style(text: str, style: TextStyle | None, link: str | None) -> str:
    """Apply markdown formatting to aggregated text.

    Args:
        text: The text to style (should be pre-aggregated for consistent styling).
        style: Text styling info.
        link: URL if this is a hyperlink.

    Returns:
        Markdown-formatted text.
    """
    result = text

    # Apply character styles
    if style:
        # Bold and italic combinations
        if style.bold and style.italic:
            result = f"***{result}***"
        elif style.bold:
            result = f"**{result}**"
        elif style.italic:
            result = f"*{result}*"

        if style.strikethrough:
            result = f"~~{result}~~"

        # Underline doesn't have standard markdown, skip it

    # Links
    if link:
        link_text = text.strip()
        if link_text:
            result = f"[{link_text}]({link})"

    return result


def get_note_json(note: Note, content: NoteContent, include_styling: bool = False) -> str:
    """Get a note as JSON string.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
        include_styling: If True, include detailed styling metadata for each run.

    Returns:
        JSON-formatted string.
    """
    # Build attachment lookup for tables
    table_lookup: dict[str, Table] = {}
    if content.attachments:
        for att in content.attachments:
            if att.table is not None:
                table_lookup[att.identifier] = att.table

    data: dict[str, object] = {
        "id": note.id,
        "title": note.title,
        "folder": note.folder,
        "created": note.created.isoformat() if note.created else None,
        "modified": note.modified.isoformat() if note.modified else None,
    }

    if include_styling and content.formatted_runs:
        # Include detailed run information
        runs_data: list[dict[str, object]] = []
        for run in content.formatted_runs:
            run_data: dict[str, object] = {
                "text": run.text,
                "length": run.length,
            }
            if run.text_style:
                run_data["style"] = {
                    "bold": run.text_style.bold,
                    "italic": run.text_style.italic,
                    "underline": run.text_style.underline,
                    "strikethrough": run.text_style.strikethrough,
                    "highlight": run.text_style.highlight,
                }
            if run.paragraph_style:
                para = run.paragraph_style
                run_data["paragraph"] = {
                    "type": para.paragraph_type,
                    "alignment": para.alignment,
                    "indent_level": para.indent_level,
                    "is_checked": para.is_checked,
                    "is_quote": para.is_quote,
                    "list_index": para.list_index,
                }
            if run.link:
                run_data["link"] = run.link
            runs_data.append(run_data)
        data["formatted_runs"] = runs_data
    else:
        # Just include plain text
        data["text"] = content.text or ""

    # Include attachments
    if content.attachments:
        attachments_data: list[dict[str, object]] = []
        for att in content.attachments:
            att_data: dict[str, object] = {
                "identifier": att.identifier,
                "type_uti": att.type_uti,
                "title": att.title,
            }
            if att.table is not None:
                # Include table data
                table = att.table
                table_data: dict[str, object] = {
                    "rows": table.rows,
                    "columns": table.columns,
                    "cells": [
                        [table.get_cell(r, c) for c in range(table.columns)]
                        for r in range(table.rows)
                    ],
                }
                att_data["table"] = table_data
            attachments_data.append(att_data)
        data["attachments"] = attachments_data

    return json.dumps(data, indent=2, ensure_ascii=False)


def display_note_json(note: Note, content: NoteContent, include_styling: bool = False) -> None:
    """Output a note as JSON.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
        include_styling: If True, include detailed styling metadata for each run.
    """
    print(get_note_json(note, content, include_styling))


def get_note_html(note: Note, content: NoteContent) -> str:
    """Get a note as a standalone HTML5 document.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.

    Returns:
        HTML5 document string.
    """
    # Build attachment lookup for tables
    table_lookup: dict[str, Table] = {}
    if content.attachments:
        for att in content.attachments:
            if att.table is not None:
                table_lookup[att.identifier] = att.table

    # Convert content to HTML
    body_html = _note_to_html(content, table_lookup)

    # Format metadata
    folder_str = note.folder or "No Folder"
    modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"

    # Build full HTML document
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(note.title)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap"
          rel="stylesheet">
    <style>
        :root {{
            --noted-purple: #5014D7;
            --noted-purple-dark: #3D0FA5;
            --noted-purple-light: #E8DEFF;
            --noted-black: #1E1E1E;
            --noted-charcoal: #5A5A5A;
            --noted-gray: #909090;
            --noted-cement: #CCCCCC;
            --noted-mist: #EAEAEA;
            --noted-white: #FFFFFF;
            --noted-yellow: #FFBE5A;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: var(--noted-black);
            background-color: var(--noted-white);
            margin: 0;
            padding: 0;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem;
        }}

        header {{
            background: linear-gradient(135deg, var(--noted-purple), var(--noted-purple-dark));
            color: var(--noted-white);
            padding: 2rem;
            margin-bottom: 2rem;
            border-radius: 0 0 8px 8px;
        }}

        header h1 {{
            margin: 0 0 0.5rem 0;
            font-weight: 500;
            font-size: 2rem;
        }}

        header .meta {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}

        article {{
            background: var(--noted-white);
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}

        h1, h2, h3 {{
            color: var(--noted-purple);
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
        }}

        h1 {{ font-size: 1.75rem; font-weight: 500; }}
        h2 {{ font-size: 1.5rem; font-weight: 500; }}
        h3 {{ font-size: 1.25rem; font-weight: 500; }}

        p {{
            margin: 0 0 1rem 0;
        }}

        a {{
            color: var(--noted-purple);
            text-decoration: none;
        }}

        a:hover {{
            text-decoration: underline;
        }}

        ul, ol {{
            margin: 0 0 1rem 0;
            padding-left: 2rem;
        }}

        li {{
            margin-bottom: 0.25rem;
        }}

        .checklist {{
            list-style: none;
            padding-left: 0;
        }}

        .checklist li {{
            display: flex;
            align-items: flex-start;
            gap: 0.5rem;
        }}

        .checklist li.checked {{
            color: var(--noted-gray);
            text-decoration: line-through;
        }}

        .checkbox {{
            color: var(--noted-purple);
            font-size: 1.1em;
        }}

        blockquote {{
            border-left: 4px solid var(--noted-purple);
            margin: 1rem 0;
            padding: 0.5rem 1rem;
            background: var(--noted-purple-light);
            border-radius: 0 4px 4px 0;
        }}

        blockquote p {{
            margin: 0;
        }}

        pre {{
            background: var(--noted-black);
            color: var(--noted-white);
            padding: 1rem;
            border-radius: 4px;
            overflow-x: auto;
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            font-size: 0.9rem;
        }}

        code {{
            background: var(--noted-mist);
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            font-size: 0.9em;
        }}

        pre code {{
            background: none;
            padding: 0;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }}

        th, td {{
            border: 1px solid var(--noted-cement);
            padding: 0.75rem;
            text-align: left;
        }}

        th {{
            background: var(--noted-purple);
            color: var(--noted-white);
            font-weight: 500;
        }}

        tr:nth-child(even) {{
            background: var(--noted-mist);
        }}

        .highlight {{
            background: var(--noted-yellow);
            padding: 0.1em 0.2em;
            border-radius: 2px;
        }}

        footer {{
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid var(--noted-cement);
            color: var(--noted-gray);
            font-size: 0.85rem;
            text-align: center;
        }}
    </style>
</head>
<body>
    <header>
        <h1>{html.escape(note.title)}</h1>
        <div class="meta">
            <span>Folder: {html.escape(folder_str)}</span> &nbsp;|&nbsp;
            <span>Modified: {modified_str}</span>
        </div>
    </header>
    <div class="container">
        <article>
{body_html}
        </article>
        <footer>
            Exported from Apple Notes by <strong>noted</strong>
        </footer>
    </div>
</body>
</html>"""

    return html_doc


def display_note_html(note: Note, content: NoteContent) -> None:
    """Output a note as a standalone HTML5 document.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
    """
    print(get_note_html(note, content))


def get_note_pdf(note: Note, content: NoteContent) -> bytes:
    """Get a note as a PDF document.

    Converts HTML representation to PDF using WeasyPrint.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.

    Returns:
        PDF document as bytes.

    Raises:
        RuntimeError: If PDF generation fails.
    """
    from weasyprint import HTML

    html_content = get_note_html(note, content)
    pdf_bytes = HTML(string=html_content).write_pdf()
    if pdf_bytes is None:
        raise RuntimeError("PDF generation failed")
    return pdf_bytes


# Image UTIs that should be rendered as inline images
_IMAGE_UTIS = {
    "public.jpeg",
    "public.png",
    "public.heic",
    "public.gif",
    "public.tiff",
    "com.compuserve.gif",
    "com.apple.drawing",
    "com.apple.drawing.2",
}


def link_attachments_html(
    content: str,
    exported_attachments: list[tuple[str, str, str]],
    attachments_dir: str,
) -> str:
    """Replace attachment markers with HTML links/images.

    Args:
        content: HTML content with markers like [Image: name] or [PDF: file.pdf].
        exported_attachments: List of (identifier, filename, type_uti) tuples.
        attachments_dir: Relative path to attachments directory.

    Returns:
        HTML with attachment markers replaced by proper elements.
    """
    if not exported_attachments:
        return content

    result = content

    for _identifier, filename, type_uti in exported_attachments:
        if not filename:
            continue

        # URL-encode the path for href/src attributes
        encoded_path = html.escape(f"{attachments_dir}/{filename}")
        display_name = html.escape(filename)

        # Build the pattern to match - escape regex special chars in filename
        # Match both [Type: filename] and [Type: title] patterns
        name_without_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
        escaped_filename = re.escape(html.escape(filename))
        escaped_name = re.escape(html.escape(name_without_ext))

        if type_uti in _IMAGE_UTIS:
            # Replace [Image: X] with <img> tag
            img_style = "max-width: 100%; height: auto;"
            replacement = f'<img src="{encoded_path}" alt="{display_name}" style="{img_style}">'
            # Try full filename first, then name without extension
            pattern = rf"\[Image: {escaped_filename}\]"
            result = re.sub(pattern, replacement, result)
            pattern = rf"\[Image: {escaped_name}\]"
            result = re.sub(pattern, replacement, result)
        else:
            # Replace [PDF: X], [Attachment: X], etc. with <a> tag
            replacement = f'<a href="{encoded_path}">📄 {display_name}</a>'
            # Match any type prefix
            pattern = rf"\[\w+: {escaped_filename}\]"
            result = re.sub(pattern, replacement, result)
            pattern = rf"\[\w+: {escaped_name}\]"
            result = re.sub(pattern, replacement, result)

    return result


def link_attachments_markdown(
    content: str,
    exported_attachments: list[tuple[str, str, str]],
    attachments_dir: str,
) -> str:
    """Replace attachment markers with Markdown links/images.

    Args:
        content: Markdown content with markers like [Image: name] or [PDF: file.pdf].
        exported_attachments: List of (identifier, filename, type_uti) tuples.
        attachments_dir: Relative path to attachments directory.

    Returns:
        Markdown with attachment markers replaced by proper syntax.
    """
    if not exported_attachments:
        return content

    result = content

    for _identifier, filename, type_uti in exported_attachments:
        if not filename:
            continue

        # URL-encode spaces and special chars for markdown links
        encoded_path = filename.replace(" ", "%20")
        full_path = f"{attachments_dir}/{encoded_path}"

        # Build patterns - match the filename or name without extension
        name_without_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
        escaped_filename = re.escape(filename)
        escaped_name = re.escape(name_without_ext)

        if type_uti in _IMAGE_UTIS:
            # Replace [Image: X] with ![alt](path)
            replacement = f"![{filename}]({full_path})"
            pattern = rf"\[Image: {escaped_filename}\]"
            result = re.sub(pattern, replacement, result)
            pattern = rf"\[Image: {escaped_name}\]"
            result = re.sub(pattern, replacement, result)
        else:
            # Replace [PDF: X], etc. with [filename](path)
            replacement = f"[📄 {filename}]({full_path})"
            pattern = rf"\[\w+: {escaped_filename}\]"
            result = re.sub(pattern, replacement, result)
            pattern = rf"\[\w+: {escaped_name}\]"
            result = re.sub(pattern, replacement, result)

    return result


def _note_to_html(
    content: NoteContent,
    table_lookup: dict[str, Table],
) -> str:
    """Convert note content to HTML body content.

    Args:
        content: Parsed note content with formatted runs.
        table_lookup: Mapping of table identifier to parsed Table.

    Returns:
        HTML string for the note body.
    """
    if not content.formatted_runs:
        return f"<p>{html.escape(content.text or '')}</p>"

    # Object replacement character
    object_replacement_char = "\ufffc"

    # Build ordered list of all attachments for matching U+FFFC occurrences
    all_attachments = content.attachments or []
    attachment_index = 0

    lines: list[str] = []
    current_paragraph: list[str] = []
    in_list: str | None = None  # 'ul', 'ol', or 'checklist'
    list_items: list[str] = []
    skip_first_title = True
    skipped_first_title = False

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph:
            text = "".join(current_paragraph).strip()
            if text:
                lines.append(f"            <p>{text}</p>")
            current_paragraph = []

    def flush_list() -> None:
        nonlocal in_list, list_items
        if list_items:
            if in_list == "checklist":
                lines.append('            <ul class="checklist">')
            elif in_list == "ol":
                lines.append("            <ol>")
            else:
                lines.append("            <ul>")
            lines.extend(list_items)
            if in_list == "ol":
                lines.append("            </ol>")
            else:
                lines.append("            </ul>")
            list_items = []
        in_list = None

    i = 0
    runs = content.formatted_runs
    while i < len(runs):
        run = runs[i]
        text = run.text
        para = run.paragraph_style
        style = run.text_style
        para_type = para.paragraph_type if para else None

        # Handle attachment placeholders (U+FFFC)
        if object_replacement_char in text:
            flush_paragraph()
            flush_list()
            if attachment_index < len(all_attachments):
                att = all_attachments[attachment_index]
                attachment_index += 1
                if att.type_uti == "com.apple.notes.table":
                    if att.identifier in table_lookup:
                        lines.append(_table_to_html(table_lookup[att.identifier]))
                else:
                    # Output marker with type and title for linking
                    type_name = _attachment_type_name(att.type_uti)
                    if att.title:
                        marker = f"[{type_name}: {html.escape(att.title)}]"
                    else:
                        marker = f"[{type_name}]"
                    lines.append(f"            <p>{marker}</p>")
            i += 1
            continue

        # Handle code blocks
        if para_type == ParagraphType.MONOSPACE:
            flush_paragraph()
            flush_list()
            code_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                if next_para and next_para.paragraph_type == ParagraphType.MONOSPACE:
                    code_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            lines.append(f"            <pre><code>{html.escape(code_text.rstrip())}</code></pre>")
            continue

        # Handle block quotes
        if para and para.is_quote:
            flush_paragraph()
            flush_list()
            quote_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                if next_para and next_para.is_quote:
                    quote_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            escaped_quote = html.escape(quote_text.strip())
            lines.append(f"            <blockquote><p>{escaped_quote}</p></blockquote>")
            continue

        # Handle lists
        if para_type in (
            ParagraphType.BULLET_LIST,
            ParagraphType.DASHED_LIST,
            ParagraphType.NUMBERED_LIST,
            ParagraphType.CHECKLIST,
        ):
            flush_paragraph()

            # Determine list type
            new_list_type = "ul"
            if para_type == ParagraphType.NUMBERED_LIST:
                new_list_type = "ol"
            elif para_type == ParagraphType.CHECKLIST:
                new_list_type = "checklist"

            # Flush if list type changed
            if in_list and in_list != new_list_type:
                flush_list()
            in_list = new_list_type

            # Collect all runs for this list item
            item_runs = [run]
            j = i + 1
            while j < len(runs) and "\n" not in runs[j - 1].text:
                next_para = runs[j].paragraph_style
                next_type = next_para.paragraph_type if next_para else None
                if next_type == para_type:
                    item_runs.append(runs[j])
                    j += 1
                else:
                    break
            i = j

            # Build item HTML
            item_html = "".join(_apply_html_style(r.text, r.text_style, r.link) for r in item_runs)
            item_html = item_html.rstrip()

            if para_type == ParagraphType.CHECKLIST:
                is_checked = para.is_checked if para else False
                checkbox = "☑" if is_checked else "☐"
                checked_class = ' class="checked"' if is_checked else ""
                checkbox_span = f'<span class="checkbox">{checkbox}</span>'
                list_items.append(
                    f"                <li{checked_class}>{checkbox_span} {item_html}</li>"
                )
            else:
                list_items.append(f"                <li>{item_html}</li>")
            continue

        # Flush list if we're no longer in a list
        if in_list and para_type not in (
            ParagraphType.BULLET_LIST,
            ParagraphType.DASHED_LIST,
            ParagraphType.NUMBERED_LIST,
            ParagraphType.CHECKLIST,
        ):
            flush_list()

        # Handle headings
        if para_type in (
            ParagraphType.TITLE,
            ParagraphType.HEADING,
            ParagraphType.SUBHEADING,
        ):
            flush_paragraph()
            flush_list()

            # Aggregate heading text
            heading_text = text
            j = i + 1
            while j < len(runs):
                next_para = runs[j].paragraph_style
                next_type = next_para.paragraph_type if next_para else None
                if next_type == para_type:
                    heading_text += runs[j].text
                    j += 1
                else:
                    break
            i = j
            heading_text = heading_text.strip()

            # Skip first title
            if para_type == ParagraphType.TITLE and skip_first_title and not skipped_first_title:
                skipped_first_title = True
                continue

            if para_type == ParagraphType.TITLE:
                lines.append(f"            <h1>{html.escape(heading_text)}</h1>")
            elif para_type == ParagraphType.HEADING:
                lines.append(f"            <h2>{html.escape(heading_text)}</h2>")
            else:
                lines.append(f"            <h3>{html.escape(heading_text)}</h3>")
            continue

        # Regular text
        styled_html = _apply_html_style(text, style, run.link)

        # Handle newlines as paragraph breaks
        if "\n" in styled_html:
            parts = styled_html.split("\n")
            current_paragraph.append(parts[0])
            flush_paragraph()
            for part in parts[1:-1]:
                if part.strip():
                    lines.append(f"            <p>{part}</p>")
            if parts[-1]:
                current_paragraph.append(parts[-1])
        else:
            current_paragraph.append(styled_html)

        i += 1

    # Flush remaining content
    flush_paragraph()
    flush_list()

    return "\n".join(lines)


def _apply_html_style(text: str, style: TextStyle | None, link: str | None) -> str:
    """Apply HTML formatting to text.

    Args:
        text: The text to style.
        style: Text styling info.
        link: URL if this is a hyperlink.

    Returns:
        HTML-formatted text.
    """
    # Escape HTML entities first
    result = html.escape(text)

    # Apply character styles
    if style:
        if style.highlight:
            result = f'<span class="highlight">{result}</span>'
        if style.strikethrough:
            result = f"<del>{result}</del>"
        if style.underline:
            result = f"<u>{result}</u>"
        if style.italic:
            result = f"<em>{result}</em>"
        if style.bold:
            result = f"<strong>{result}</strong>"

    # Links
    if link:
        result = f'<a href="{html.escape(link)}">{result}</a>'

    return result


def _table_to_html(table: Table) -> str:
    """Convert Table to HTML.

    Args:
        table: Parsed table data.

    Returns:
        HTML table string.
    """
    if table.rows == 0 or table.columns == 0:
        return ""

    lines = ["            <table>"]

    # Header row
    lines.append("                <thead>")
    lines.append("                    <tr>")
    for col in range(table.columns):
        cell = table.get_cell(0, col) or ""
        lines.append(f"                        <th>{html.escape(cell)}</th>")
    lines.append("                    </tr>")
    lines.append("                </thead>")

    # Data rows
    if table.rows > 1:
        lines.append("                <tbody>")
        for row in range(1, table.rows):
            lines.append("                    <tr>")
            for col in range(table.columns):
                cell = table.get_cell(row, col) or ""
                lines.append(f"                        <td>{html.escape(cell)}</td>")
            lines.append("                    </tr>")
        lines.append("                </tbody>")

    lines.append("            </table>")
    return "\n".join(lines)
