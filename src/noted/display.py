"""Terminal display formatting using Rich."""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table as RichTable
from rich.text import Text

from noted.models import Note, NoteContent, NoteSummary, Table

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

    # Print body text
    if content.text:
        console.print(content.text)
    else:
        console.print("[dim]No content[/dim]")


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
