"""CLI commands for noted using Typer."""

import typer
from loguru import logger

from noted import db, display

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


if __name__ == "__main__":
    app()
