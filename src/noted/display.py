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

from noted.models import (
    FormattedRun,
    Note,
    NoteContent,
    NoteSummary,
    ParagraphType,
    Table,
    TextAlignment,
    TextStyle,
)

console = Console()


def display_notes_table(notes: list[Note]) -> None:
    """Render notes as a Rich table.

    Args:
        notes: List of notes to display.
    """
    if not notes:
        console.print("[yellow]No notes found.[/yellow]")
        return

    table = RichTable(title="Notes", show_lines=False)
    table.add_column("ID", style="dim", width=6)
    table.add_column("Title", style="bold")
    table.add_column("Folder", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Modified", style="green")

    for note in notes:
        created_str = note.created.strftime("%Y-%m-%d %H:%M") if note.created else "-"
        modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"
        table.add_row(
            str(note.id),
            note.title,
            note.folder or "(No Folder)",
            created_str,
            modified_str,
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(notes)} notes[/dim]")


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
    table_identifiers: list[str] = []
    if content.attachments:
        for att in content.attachments:
            if att.type_uti == "com.apple.notes.table":
                table_identifiers.append(att.identifier)
                if att.table is not None:
                    table_lookup[att.identifier] = att.table

    # Use formatted rendering if available
    if content.formatted_runs:
        _render_formatted_content(content.formatted_runs, table_lookup, table_identifiers)
    elif content.text:
        _render_text_with_tables(content.text, table_lookup)
    else:
        console.print("[dim]No content[/dim]")


def _render_formatted_content(
    runs: list[FormattedRun],
    table_lookup: dict[str, Table],
    table_identifiers: list[str],
) -> None:
    """Render formatted content with rich styling.

    Args:
        runs: List of formatted text runs.
        table_lookup: Mapping of table identifier to parsed Table.
        table_identifiers: Ordered list of table attachment identifiers.
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

        # Handle attachment placeholders (U+FFFC) - tables
        if object_replacement_char in text:
            if attachment_index < len(table_identifiers):
                identifier = table_identifiers[attachment_index]
                attachment_index += 1
                if identifier in table_lookup:
                    rich_table = table_to_rich(table_lookup[identifier])
                    console.print(rich_table)
                else:
                    console.print("[Table]", end="")
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


def display_note_markdown(note: Note, content: NoteContent) -> None:
    """Output a note as raw markdown text.

    Outputs plain markdown that can be piped to tools like glow,
    copied to Notion, or saved to a .md file.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
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
    full_md = f"# {note.title}\n\n{md_text}"

    # Output raw markdown (no Rich formatting)
    print(full_md)


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

    # Build list of table attachments in order for matching U+FFFC occurrences
    table_attachments: list[str] = []
    if content.attachments:
        for att in content.attachments:
            if att.type_uti == "com.apple.notes.table":
                table_attachments.append(att.identifier)
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
            # Look up table by attachment order
            if attachment_index < len(table_attachments):
                identifier = table_attachments[attachment_index]
                attachment_index += 1
                if identifier in table_lookup:
                    lines.append(table_to_markdown(table_lookup[identifier]))
                else:
                    lines.append("[Table]")
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
            if (
                para_type == ParagraphType.TITLE
                and skip_first_title
                and not skipped_first_title
            ):
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
        has_styling = style and (
            style.bold or style.italic or style.strikethrough
        )
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


def display_note_json(
    note: Note, content: NoteContent, include_styling: bool = False
) -> None:
    """Output a note as JSON.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
        include_styling: If True, include detailed styling metadata for each run.
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

    print(json.dumps(data, indent=2, ensure_ascii=False))


def display_note_html(note: Note, content: NoteContent) -> None:
    """Output a note as a standalone HTML5 document with Adeia branding.

    Args:
        note: Note metadata (title, folder, dates).
        content: Parsed note content.
    """
    # Build attachment lookup for tables
    table_lookup: dict[str, Table] = {}
    if content.attachments:
        for att in content.attachments:
            if att.table is not None:
                table_lookup[att.identifier] = att.table

    # Build table identifiers list for U+FFFC handling
    table_identifiers: list[str] = []
    if content.attachments:
        for att in content.attachments:
            if att.type_uti == "com.apple.notes.table":
                table_identifiers.append(att.identifier)

    # Convert content to HTML
    body_html = _note_to_html(content, table_lookup, table_identifiers)

    # Format metadata
    folder_str = note.folder or "No Folder"
    modified_str = note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "-"

    # Build full HTML document with Adeia branding
    html_doc = f'''<!DOCTYPE html>
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
            --adeia-purple: #5014D7;
            --adeia-purple-dark: #3D0FA5;
            --adeia-purple-light: #E8DEFF;
            --adeia-black: #1E1E1E;
            --adeia-charcoal: #5A5A5A;
            --adeia-gray: #909090;
            --adeia-cement: #CCCCCC;
            --adeia-mist: #EAEAEA;
            --adeia-white: #FFFFFF;
            --adeia-yellow: #FFBE5A;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: var(--adeia-black);
            background-color: var(--adeia-white);
            margin: 0;
            padding: 0;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem;
        }}

        header {{
            background: linear-gradient(135deg, var(--adeia-purple), var(--adeia-purple-dark));
            color: var(--adeia-white);
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
            background: var(--adeia-white);
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}

        h1, h2, h3 {{
            color: var(--adeia-purple);
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
            color: var(--adeia-purple);
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
            color: var(--adeia-gray);
            text-decoration: line-through;
        }}

        .checkbox {{
            color: var(--adeia-purple);
            font-size: 1.1em;
        }}

        blockquote {{
            border-left: 4px solid var(--adeia-purple);
            margin: 1rem 0;
            padding: 0.5rem 1rem;
            background: var(--adeia-purple-light);
            border-radius: 0 4px 4px 0;
        }}

        blockquote p {{
            margin: 0;
        }}

        pre {{
            background: var(--adeia-black);
            color: var(--adeia-white);
            padding: 1rem;
            border-radius: 4px;
            overflow-x: auto;
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            font-size: 0.9rem;
        }}

        code {{
            background: var(--adeia-mist);
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
            border: 1px solid var(--adeia-cement);
            padding: 0.75rem;
            text-align: left;
        }}

        th {{
            background: var(--adeia-purple);
            color: var(--adeia-white);
            font-weight: 500;
        }}

        tr:nth-child(even) {{
            background: var(--adeia-mist);
        }}

        .highlight {{
            background: var(--adeia-yellow);
            padding: 0.1em 0.2em;
            border-radius: 2px;
        }}

        footer {{
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid var(--adeia-cement);
            color: var(--adeia-gray);
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
</html>'''

    print(html_doc)


def _note_to_html(
    content: NoteContent,
    table_lookup: dict[str, Table],
    table_identifiers: list[str],
) -> str:
    """Convert note content to HTML body content.

    Args:
        content: Parsed note content with formatted runs.
        table_lookup: Mapping of table identifier to parsed Table.
        table_identifiers: Ordered list of table attachment identifiers.

    Returns:
        HTML string for the note body.
    """
    if not content.formatted_runs:
        return f"<p>{html.escape(content.text or '')}</p>"

    # Object replacement character
    object_replacement_char = "\ufffc"
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

        # Handle attachment placeholders (U+FFFC) - tables
        if object_replacement_char in text:
            flush_paragraph()
            flush_list()
            if attachment_index < len(table_identifiers):
                identifier = table_identifiers[attachment_index]
                attachment_index += 1
                if identifier in table_lookup:
                    lines.append(_table_to_html(table_lookup[identifier]))
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
