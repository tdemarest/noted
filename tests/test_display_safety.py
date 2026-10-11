"""Guard tests: note data is shown literally and in full by noted.display.

Note, folder and attachment text comes from the user's database and must never be
parsed as Rich markup, and the never-truncate rule means no text may be cut off.
"""

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from rich.console import Console

from noted import display
from noted.db import FolderInfo
from noted.models import (
    Attachment,
    DatabaseStats,
    FormattedRun,
    Note,
    NoteContent,
    ParagraphStyle,
    ParagraphType,
    SearchResult,
    Table,
)

MARKUP_TITLE = "[bold]Plan[/bold] [red]x[/red]"
SHORT_MARKUP_TITLE = "[bold]P[/bold]"
SHORT_MARKUP_FOLDER = "[cyan]W[/cyan]"
LONG_TOKEN = "Token" + "0123456789" * 8
ELLIPSIS = chr(0x2026)
HEAVY_BAR = chr(0x2503)
LIGHT_BAR = chr(0x2502)


@pytest.fixture
def recorded() -> Iterator[Console]:
    """Swap the display console for a plain, recording one.

    Yields:
        The recording console; read its output with ``export_text()``.
    """
    rec = Console(record=True, width=200, file=io.StringIO(), color_system=None)
    with patch.object(display, "console", rec):
        yield rec


def _note(title: str = MARKUP_TITLE, folder: str | None = "[cyan]Work[/cyan]") -> Note:
    """Build a synthetic note.

    Args:
        title: Note title.
        folder: Note folder name.

    Returns:
        A Note with fixed dates.
    """
    return Note(
        id=42,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title=title,
        folder=folder,
        created=datetime(2025, 1, 15, 10, 30, tzinfo=UTC),
        modified=datetime(2025, 1, 28, 14, 45, tzinfo=UTC),
    )


def _stats(
    folder_counts: dict[str, int] | None = None,
    attachment_type_counts: dict[str, int] | None = None,
) -> DatabaseStats:
    """Build synthetic database stats.

    Args:
        folder_counts: Per-folder note counts.
        attachment_type_counts: Attachment counts by UTI.

    Returns:
        A DatabaseStats instance.
    """
    types = attachment_type_counts or {}
    return DatabaseStats(
        total_notes=1,
        pinned_notes=0,
        locked_notes=0,
        deleted_notes=0,
        notes_with_checklists=0,
        notes_with_incomplete_checklists=0,
        folder_counts=folder_counts or {},
        total_attachments=sum(types.values()),
        attachment_type_counts=types,
        attachments_with_location=0,
        database_size_bytes=0,
        cache_modified=None,
        fts_index_size_bytes=0,
        fts_index_built_at=None,
        fts_index_fresh=False,
        fts_indexed_notes=0,
    )


def _column_text(out: str, header: str) -> str:
    """Join the wrapped lines of one table column back into a single string.

    Uses the header row's vertical borders to find the column's character range,
    then concatenates that slice of every body row.

    Args:
        out: Recorded console output containing one heavy-header Rich table.
        header: Text of the column header.

    Returns:
        The column's body text with the wrap whitespace removed.
    """
    lines = out.splitlines()
    head_idx = next(i for i, line in enumerate(lines) if HEAVY_BAR in line and header in line)
    head = lines[head_idx]
    bars = [i for i, ch in enumerate(head) if ch == HEAVY_BAR]
    pos = head.index(header)
    left = max(b for b in bars if b < pos)
    right = min(b for b in bars if b > pos)
    body = [
        line for line in lines[head_idx + 2 :] if len(line) > right and line[right] == LIGHT_BAR
    ]
    return "".join(line[left + 1 : right].strip() for line in body)


def test_attachment_title_markup_is_literal(recorded: Console) -> None:
    """Test an attachment title that looks like markup prints verbatim in brackets."""
    att = Attachment(identifier="att-1", type_uti="public.jpeg", title="[bold]")
    att2 = Attachment(identifier="att-2", type_uti="public.jpeg", title="[red]x[/red]")
    runs = [
        FormattedRun(text="￼", length=1, attachment_identifier="att-1"),
        FormattedRun(text="￼", length=1, attachment_identifier="att-2"),
    ]
    content = NoteContent(text="￼￼", attachments=[att, att2], formatted_runs=runs)

    display.display_note_view(_note(), content)

    out = recorded.export_text()
    assert "[[bold]]" in out
    assert "[[red]x[/red]]" in out


def test_note_view_text_markup_is_literal(recorded: Console) -> None:
    """Test the panel title, headings and body text print verbatim."""
    runs = [
        FormattedRun(
            text="[bold]Heading[/bold]\n",
            length=20,
            paragraph_style=ParagraphStyle(paragraph_type=ParagraphType.HEADING),
        ),
        FormattedRun(text="body [i]text[/i] :smile:\n", length=24),
    ]
    display.display_note_view(_note(), NoteContent(text="", formatted_runs=runs))

    out = recorded.export_text()
    assert MARKUP_TITLE in out
    assert "[bold]Heading[/bold]" in out
    assert "body [i]text[/i] :smile:" in out


def test_plain_text_and_table_cells_are_literal(recorded: Console) -> None:
    """Test unformatted note text and table cells print verbatim."""
    table = Table(rows=1, columns=1, cells={(0, 0): "[green]cell[/green]"})
    att = Attachment(identifier="T1", type_uti="com.apple.notes.table", table=table)
    content = NoteContent(text="[bold]before[/bold] [Table:T1] [dim]after[/dim]", attachments=[att])

    display.display_note_view(_note(), content)

    out = recorded.export_text()
    assert "[bold]before[/bold]" in out
    assert "[green]cell[/green]" in out
    assert "[dim]after[/dim]" in out


def test_tree_labels_are_literal(recorded: Console) -> None:
    """Test folder and note names in the tree view print verbatim."""
    folders = [
        FolderInfo(
            name="[red]Projects", identifier="F1", note_count=1, path="[red]Projects", folder_type=0
        )
    ]
    note = _note(title="[bold]Plan", folder="[red]Projects")

    display.display_notes_tree(folders, [note], verbose=True)

    out = recorded.export_text()
    assert "[red]Projects (1)" in out
    assert "[bold]Plan" in out


def test_search_debug_and_stats_tables_are_literal(recorded: Console) -> None:
    """Test note data in the search, debug and per-folder stats tables prints verbatim."""
    note = _note(title=SHORT_MARKUP_TITLE, folder=SHORT_MARKUP_FOLDER)
    display.display_search_results([SearchResult(note=note, snippet="x", rank=1.0)], "q")
    display.display_debug_note_info(_note())
    display.display_stats(_stats(folder_counts={"[bold]Inbox[/bold]": 1}))

    out = recorded.export_text()
    assert out.count(SHORT_MARKUP_TITLE) == 1
    assert out.count(SHORT_MARKUP_FOLDER) == 1
    assert MARKUP_TITLE in out
    assert "[cyan]Work[/cyan]" in out
    assert "[bold]Inbox[/bold]" in out


def test_export_status_lines_and_messages_are_literal(recorded: Console) -> None:
    """Test export progress lines, the issues summary and messages print verbatim."""
    display.display_export_success("[cyan]Work[/cyan]", MARKUP_TITLE, 2)
    display.display_export_locked(None, MARKUP_TITLE)
    display.display_export_failed("Work", MARKUP_TITLE, "[red]boom[/red]")
    display.display_export_issues_summary(
        [("Work", MARKUP_TITLE)], [("Work", MARKUP_TITLE, "[red]boom[/red]")]
    )
    display.display_error("Note '[bold]1[/bold]' not found.")

    out = recorded.export_text()
    assert f"[cyan]Work[/cyan]/{MARKUP_TITLE} (2 attachments)" in out
    assert out.count(MARKUP_TITLE) == 5
    assert "(failed: [red]boom[/red])" in out
    assert "([red]boom[/red])" in out
    assert "Note '[bold]1[/bold]' not found." in out


def test_search_results_long_tokens_not_truncated(recorded: Console) -> None:
    """Test fixed-width search columns fold long tokens instead of cutting them."""
    note = _note(title=LONG_TOKEN, folder=LONG_TOKEN)
    display.display_search_results(
        [SearchResult(note=note, snippet=f"<<<{LONG_TOKEN}>>>", rank=1.0)], "q"
    )

    out = recorded.export_text()
    assert ELLIPSIS not in out
    assert _column_text(out, "Title") == LONG_TOKEN
    assert _column_text(out, "Folder") == LONG_TOKEN
    assert _column_text(out, "Match Context") == LONG_TOKEN


def test_notes_table_long_id_not_truncated(recorded: Console) -> None:
    """Test the fixed-width ID column folds a long ID instead of cutting it."""
    note = _note(title="T", folder="F")
    note.id = 123456789012

    display.display_notes_table([note])

    out = recorded.export_text()
    assert ELLIPSIS not in out
    assert _column_text(out, "ID") == "123456789012"


def test_code_block_long_line_not_cropped() -> None:
    """Test a monospace line wider than the terminal wraps instead of being cropped."""
    rec = Console(record=True, width=40, file=io.StringIO(), color_system=None)
    runs = [
        FormattedRun(
            text=f"{LONG_TOKEN}\n",
            length=len(LONG_TOKEN) + 1,
            paragraph_style=ParagraphStyle(paragraph_type=ParagraphType.MONOSPACE),
        )
    ]
    with patch.object(display, "console", rec):
        display.display_note_view(_note(), NoteContent(text="", formatted_runs=runs))

    out = rec.export_text()
    assert "".join(line.strip() for line in out.splitlines()).count(LONG_TOKEN) == 1


def test_stats_lists_every_image_subtype(recorded: Console) -> None:
    """Test the image subtype breakdown lists all subtypes, not the first four."""
    counts = {
        "public.jpeg": 6,
        "public.png": 5,
        "public.heic": 4,
        "public.gif": 3,
        "public.tiff": 2,
        "org.webmproject.webp": 1,
    }

    display.display_stats(_stats(attachment_type_counts=counts))

    out = recorded.export_text()
    assert "TIFF: 2" in out
    assert "WebP: 1" in out
    assert "..." not in out
