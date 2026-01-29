"""CLI commands for noted using Typer."""

import typer
from loguru import logger

from noted import db, display, protobuf, tables

app = typer.Typer(
    name="noted",
    help="CLI tool for working with Apple Notes database.",
    no_args_is_help=True,
)


@app.command()
def list(
    folder: str | None = typer.Option(
        None,
        "--folder",
        "-f",
        help="Filter by folder name.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        help="Limit number of results.",
    ),
) -> None:
    """List all notes."""
    try:
        conn = db.get_connection()
        notes = db.list_notes(conn, folder=folder, limit=limit)
        display.display_notes_table(notes)
        conn.close()
    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.exception("Error listing notes")
        display.display_error(str(e))
        raise typer.Exit(code=1)


@app.command()
def count(
    by_folder: bool = typer.Option(
        False,
        "--by-folder",
        "-f",
        help="Show counts per folder.",
    ),
) -> None:
    """Count total notes."""
    try:
        conn = db.get_connection()
        summary = db.get_summary(conn, by_folder=by_folder)
        display.display_count(summary)
        conn.close()
    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.exception("Error counting notes")
        display.display_error(str(e))
        raise typer.Exit(code=1)


@app.command()
def refresh() -> None:
    """Force refresh the cached database copy."""
    db.clear_cache()
    display.display_success("Cache cleared. Next command will use fresh data.")


@app.command()
def view(
    note_id: int = typer.Argument(..., help="Note ID to view (from list command)."),
) -> None:
    """View the full content of a note."""
    try:
        conn = db.get_connection()

        # Get note metadata
        note = db.get_note_by_id(conn, note_id)
        if note is None:
            display.display_error(f"Note with ID {note_id} not found.")
            conn.close()
            raise typer.Exit(code=1)

        # Get note content
        raw_data = db.get_note_content(conn, note_id)

        if raw_data is None:
            conn.close()
            display.display_error("Note has no content.")
            raise typer.Exit(code=1)

        # Check if locked
        if protobuf.is_note_locked(raw_data):
            conn.close()
            display.display_error("Note is locked and cannot be read.")
            raise typer.Exit(code=1)

        # Get attachment names for display
        attachment_names = db.get_attachment_names(conn, note_id)

        # Parse content with formatting
        content = protobuf.parse_note_data(
            raw_data,
            attachment_names,
            include_formatting=True,
        )

        # Parse table attachments
        if content.attachments:
            for attachment in content.attachments:
                if attachment.type_uti == "com.apple.notes.table":
                    result = db.get_table_data(conn, attachment.identifier)
                    if result:
                        table_data, summary = result
                        attachment.table = tables.parse_table_data(table_data, summary)

        conn.close()

        # Display
        display.display_note_view(note, content)

    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Error viewing note")
        display.display_error(str(e))
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
