"""Terminal display formatting using Rich."""

from rich.console import Console
from rich.table import Table

from noted.models import Note, NoteSummary

console = Console()


def display_notes_table(notes: list[Note]) -> None:
    """Render notes as a Rich table.

    Args:
        notes: List of notes to display.
    """
    if not notes:
        console.print("[yellow]No notes found.[/yellow]")
        return

    table = Table(title="Notes", show_lines=False)
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
        table = Table(show_header=True, header_style="bold")
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
