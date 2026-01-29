"""Terminal display formatting using Rich."""

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
    if content.attachments:
        for att in content.attachments:
            if att.table is not None:
                table_lookup[att.identifier] = att.table

    # Use formatted rendering if available
    if content.formatted_runs:
        _render_formatted_content(content.formatted_runs, table_lookup)
    elif content.text:
        _render_text_with_tables(content.text, table_lookup)
    else:
        console.print("[dim]No content[/dim]")


def _render_formatted_content(
    runs: list[FormattedRun],
    table_lookup: dict[str, Table],
) -> None:
    """Render formatted content with rich styling.

    Args:
        runs: List of formatted text runs.
        table_lookup: Mapping of table identifier to parsed Table.
    """
    # Table marker pattern
    table_pattern = re.compile(r"\[Table:([^\]]+)\]")

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

        # Check for table markers
        table_match = table_pattern.search(text)
        if table_match:
            identifier = table_match.group(1)
            if identifier in table_lookup:
                rich_table = table_to_rich(table_lookup[identifier])
                console.print(rich_table)
            else:
                console.print("[Table]", end="")
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

            # Build the item text with styling
            item_text = Text()
            for r in item_runs:
                char_style = _get_char_style(r.text_style, r.link)
                item_text.append(r.text, style=char_style or None)

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

        # Handle alignment
        if para and para.alignment == TextAlignment.CENTER:
            console.print(text, style=char_style or None, justify="center", end="")
        elif para and para.alignment == TextAlignment.RIGHT:
            console.print(text, style=char_style or None, justify="right", end="")
        else:
            console.print(text, style=char_style or None, end="")

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
