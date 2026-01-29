"""CLI commands for noted using Typer."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from rich.console import Console

from noted import attachments, db, display, protobuf, search, tables
from noted import export as export_module

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
    search_query: str | None = typer.Option(
        None,
        "--search",
        "-s",
        help=(
            "Search query. Without --deep: case-insensitive title/folder match. "
            "With --deep: FTS5 full-text search supporting: "
            'phrases ("exact phrase"), '
            "boolean (AND, OR, NOT - uppercase), "
            "grouping with parentheses, "
            "prefix (budg*), "
            "column filters (title:, folder:, content:)."
        ),
    ),
    deep: bool = typer.Option(
        False,
        "--deep",
        "-D",
        help="Search note content using FTS5 full-text search (requires --search).",
    ),
) -> None:
    """List all notes."""
    # Validate: --deep requires --search
    if deep and search_query is None:
        display.display_error("--deep requires --search to be specified.")
        raise typer.Exit(code=1)

    try:
        conn = db.get_connection()

        if deep and search_query:
            # Deep content search using FTS5
            results = search.search_notes(conn, search_query, folder=folder, limit=limit)
            display.display_search_results(results, search_query)
        else:
            # Standard title/folder search
            notes = db.list_notes(conn, folder=folder, limit=limit, search=search_query)
            display.display_notes_table(notes, search=search_query)

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
    """Force refresh the cached database copy and FTS index."""
    db.clear_cache()
    search.clear_index()
    display.display_success("Cache and FTS index cleared. Next command will use fresh data.")


@app.command()
def index(
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        "-r",
        help="Force rebuild the FTS index.",
    ),
) -> None:
    """Show FTS index status or rebuild."""
    try:
        if rebuild:
            conn = db.get_connection()
            count = search.build_index(conn, show_progress=True)
            conn.close()
            display.display_success(f"FTS index rebuilt with {count} notes.")
        else:
            # Show index status
            status = search.get_index_status()

            if not status["exists"]:
                console.print("[yellow]FTS index does not exist.[/yellow]")
                console.print("Run [bold]noted index --rebuild[/bold] to create it.")
                console.print("Or run a deep search with [bold]--deep[/bold] to auto-create.")
            else:
                fresh_str = "[green]fresh[/green]" if status["fresh"] else "[yellow]stale[/yellow]"
                console.print(f"[bold]FTS Index Status:[/bold] {fresh_str}")

                if "note_count" in status:
                    console.print(f"  Notes indexed: {status['note_count']}")
                if "built_at" in status:
                    console.print(f"  Built at: {status['built_at']}")
                if "size_bytes" in status:
                    size_bytes = int(status["size_bytes"])
                    size_kb = size_bytes / 1024
                    if size_kb >= 1024:
                        size_str = f"{size_kb / 1024:.1f} MB"
                    else:
                        size_str = f"{size_kb:.1f} KB"
                    console.print(f"  Index size: {size_str}")

                if not status["fresh"]:
                    console.print(
                        "\n[dim]Index is stale. Run [bold]noted index --rebuild[/bold] "
                        "or it will auto-rebuild on next deep search.[/dim]"
                    )
    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.exception("Error managing FTS index")
        display.display_error(str(e))
        raise typer.Exit(code=1)


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
    export_path: Path | None = typer.Option(
        None,
        "--export",
        "-o",
        help="Export to file (extension auto-selected based on format).",
    ),
) -> None:
    """View the full content of a note.

    For exporting notes with attachments, use the 'export' command instead.
    """
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

        conn.close()

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

        # Export to file or display
        if export_path:
            # Add extension if not provided
            final_path = export_path if export_path.suffix else export_path.with_suffix(ext)
            if output is not None:
                final_path.write_text(output, encoding="utf-8")
            else:
                # For rich text, export as plain text
                final_path.write_text(content.text or "", encoding="utf-8")
            display.display_success(f"Exported to {final_path}")
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


@app.command()
def export(
    note_ref: str | None = typer.Argument(
        None,
        help="Note ID or UUID to export. Omit for --all.",
    ),
    all_notes: bool = typer.Option(
        False,
        "--all",
        "-A",
        help="Export all notes.",
    ),
    output: Path = typer.Option(
        Path("./notes_export"),
        "--output",
        "-o",
        help="Output directory.",
    ),
    zip_archive: bool = typer.Option(
        False,
        "--zip",
        "-z",
        help="Also create 7zip archive.",
    ),
    folder_filter: str | None = typer.Option(
        None,
        "--folder",
        "-f",
        help="Export only notes from this folder.",
    ),
    exclude_deleted: bool = typer.Option(
        False,
        "--exclude-deleted",
        help="Exclude notes in Recently Deleted.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed output for each note.",
    ),
) -> None:
    """Export notes to markdown with attachments."""
    # Validate: need either --all or note_ref
    if not all_notes and note_ref is None:
        display.display_error("Specify either --all or a note ID/UUID to export.")
        raise typer.Exit(code=1)

    if all_notes and note_ref is not None:
        display.display_error("Cannot use --all with a specific note ID.")
        raise typer.Exit(code=1)

    try:
        conn = db.get_connection()

        if all_notes:
            # Full export
            options = export_module.ExportOptions(
                output_dir=output,
                include_deleted=not exclude_deleted,
                create_archive=zip_archive,
                folder_filter=folder_filter,
                verbose=verbose,
            )

            result = export_module.export_all_notes(conn, options)
            conn.close()

            # Display summary
            display.display_success(
                f"Exported {result.exported_count} notes to {result.output_dir}"
            )
            if result.locked_count > 0:
                display.display_warning(
                    f"{result.locked_count} locked notes (placeholders created)"
                )
            if result.failed_count > 0:
                display.display_error(f"{result.failed_count} notes failed (see index.json)")
            if result.total_attachments > 0:
                console.print(f"[dim]Total attachments: {result.total_attachments}[/dim]")
            if result.archive_path:
                display.display_success(f"Created archive: {result.archive_path}")

        else:
            # Single note export
            assert note_ref is not None  # Validated above
            note = db.get_note(conn, note_ref)
            if note is None:
                display.display_error(f"Note '{note_ref}' not found.")
                conn.close()
                raise typer.Exit(code=1)

            # Use flat structure for single note (like old view --attachments)
            base_name = attachments.sanitize_filename(note.title)
            # If default output, use current directory with note name
            if output == Path("./notes_export"):
                base_path = Path.cwd() / base_name
            else:
                base_path = output.with_suffix("")

            # Get note content
            raw_data = db.get_note_content(conn, note.id)
            if raw_data is None:
                conn.close()
                display.display_error("Note has no content.")
                raise typer.Exit(code=1)

            if protobuf.is_note_locked(raw_data):
                conn.close()
                display.display_error("Note is locked and cannot be exported.")
                raise typer.Exit(code=1)

            # Parse and export
            attachment_names = db.get_attachment_names(conn, note.id)
            content = protobuf.parse_note_data(raw_data, attachment_names, include_formatting=True)

            if content.attachments:
                for attachment in content.attachments:
                    if attachment.type_uti == "com.apple.notes.table":
                        table_result = db.get_table_data(conn, attachment.identifier)
                        if table_result:
                            table_data, summary = table_result
                            attachment.table = tables.parse_table_data(table_data, summary)

            # Write markdown
            markdown = display.get_note_markdown(note, content)
            note_path = base_path.with_suffix(".md")
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(markdown, encoding="utf-8")

            # Export attachments
            att_result = attachments.AttachmentExportResult(
                exported=[], skipped=[], manifest_path=None, attachments_dir=None
            )
            if content.attachments:
                att_result = attachments.export_attachments(
                    conn=conn,
                    attachments=content.attachments,
                    output_dir=base_path.parent,
                    base_name=base_name,
                    note=note,
                )

            conn.close()

            # Create archive if requested
            if zip_archive:
                archive_path = attachments.create_archive(
                    base_path, note_path, att_result.attachments_dir
                )
                display.display_success(f"Created archive: {archive_path}")
            else:
                display.display_success(f"Exported to {note_path}")

            if att_result.exported:
                display.display_success(f"Exported {len(att_result.exported)} attachments")
            if att_result.skipped:
                from collections import Counter

                type_counts = Counter(
                    protobuf.UTI_TYPE_MAP.get(a.type_uti, "Unknown") for a in att_result.skipped
                )
                summary = ", ".join(f"{v} {k}" for k, v in type_counts.items())
                display.display_warning(
                    f"Skipped {len(att_result.skipped)} non-exportable: {summary}"
                )

    except FileNotFoundError:
        display.display_error("Apple Notes database not found.")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Error exporting notes")
        display.display_error(str(e))
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
