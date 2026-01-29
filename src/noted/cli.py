"""CLI commands for noted using Typer."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from rich.console import Console

from noted import db, display, protobuf, tables

# Debug mode state (set by callback)
_debug_mode = False

console = Console(stderr=True)


def _debug_callback(debug: bool) -> None:
    """Configure logging based on debug flag.

    Args:
        debug: Whether debug mode is enabled.
    """
    global _debug_mode
    _debug_mode = debug

    # Remove default handler and reconfigure
    logger.remove()
    if debug:
        logger.add(
            sys.stderr,
            level="DEBUG",
            format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <8}</level> | {message}",
            colorize=True,
        )
    else:
        logger.add(
            sys.stderr,
            level="WARNING",
            format="<level>{level}</level>: {message}",
            colorize=True,
        )


app = typer.Typer(
    name="noted",
    help="CLI tool for working with Apple Notes database.",
    no_args_is_help=True,
    callback=lambda debug: _debug_callback(debug),
)


@app.callback()
def main(
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            "-d",
            help="Enable verbose debug output.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """CLI tool for working with Apple Notes database."""
    _debug_callback(debug)


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
    note_ref: str = typer.Argument(..., help="Note ID or UUID to view (from list command)."),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        "-md",
        help="Output as raw markdown text.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON.",
    ),
    json_styled: bool = typer.Option(
        False,
        "--json-styled",
        help="Include styling metadata in JSON output.",
    ),
    html: bool = typer.Option(
        False,
        "--html",
        help="Output as standalone HTML5 document.",
    ),
    export: Path | None = typer.Option(
        None,
        "--export",
        "-o",
        help="Export to file (extension auto-selected based on format).",
    ),
    attachments_flag: bool = typer.Option(
        False,
        "--attachments",
        "-a",
        help="Export attachments alongside note file.",
    ),
    zip_archive: bool = typer.Option(
        False,
        "--zip",
        "-z",
        help="Compress output as 7zip archive (requires --attachments).",
    ),
) -> None:
    """View the full content of a note."""
    # Validate options
    if zip_archive and not attachments_flag:
        display.display_error("--zip requires --attachments")
        raise typer.Exit(code=1)

    try:
        conn = db.get_connection()

        # Get note metadata (accepts either row ID or UUID)
        note = db.get_note(conn, note_ref)
        if note is None:
            display.display_error(f"Note '{note_ref}' not found.")
            conn.close()
            raise typer.Exit(code=1)

        # Debug output: show note identifiers and attachment stats
        if _debug_mode:
            attachment_stats = db.get_attachment_stats(conn, note.id)
            display.display_debug_note_info(note, attachment_stats)

        # Get note content using the resolved row ID
        raw_data = db.get_note_content(conn, note.id)

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
        attachment_names = db.get_attachment_names(conn, note.id)

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

        # Determine output format and get content
        if json_output or json_styled:
            output = display.get_note_json(note, content, include_styling=json_styled)
            ext = ".json"
        elif html:
            output = display.get_note_html(note, content)
            ext = ".html"
        elif markdown:
            output = display.get_note_markdown(note, content)
            ext = ".md"
        else:
            output = None  # Rich text display handled separately
            ext = ".txt"

        # Handle attachments export
        if attachments_flag:
            from collections import Counter

            from noted import attachments as att_module

            # Determine base path
            if export:
                base_path = export.with_suffix("")
            else:
                base_path = Path.cwd() / att_module.sanitize_filename(note.title)

            # Ensure we have markdown output for export (default if none specified)
            if output is None:
                output = display.get_note_markdown(note, content)
                ext = ".md"

            # Write note file
            note_path = base_path.with_suffix(ext)
            note_path.write_text(output, encoding="utf-8")

            # Export attachments
            export_result = att_module.AttachmentExportResult(
                exported=[], skipped=[], manifest_path=None, attachments_dir=None
            )
            if content.attachments:
                export_result = att_module.export_attachments(
                    conn=conn,
                    attachments=content.attachments,
                    output_dir=base_path.parent,
                    base_name=base_path.name,
                    note=note,
                )

            conn.close()

            # Create archive if requested
            if zip_archive:
                archive_path = att_module.create_archive(
                    base_path, note_path, export_result.attachments_dir
                )
                display.display_success(f"Created archive: {archive_path}")
            else:
                display.display_success(f"Exported to {note_path}")

            # Report attachment results
            if export_result.exported:
                display.display_success(f"Exported {len(export_result.exported)} attachments")
            if export_result.skipped:
                # Summarize skipped by type
                type_counts = Counter(
                    protobuf.UTI_TYPE_MAP.get(a.type_uti, "Unknown") for a in export_result.skipped
                )
                summary = ", ".join(f"{v} {k}" for k, v in type_counts.items())
                display.display_warning(
                    f"Skipped {len(export_result.skipped)} non-exportable: {summary}"
                )

        else:
            conn.close()

            # Export to file or display
            if export:
                # Add extension if not provided
                export_path = export if export.suffix else export.with_suffix(ext)
                if output is not None:
                    export_path.write_text(output, encoding="utf-8")
                else:
                    # For rich text, export as plain text
                    export_path.write_text(content.text or "", encoding="utf-8")
                display.display_success(f"Exported to {export_path}")
            elif output is not None:
                print(output)
            else:
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
