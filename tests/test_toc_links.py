"""Tests for heading anchors, --toc output, bare-URL links and link scheme safety."""

import io
import json
import re
import zlib
from unittest.mock import patch

import pytest
from rich.console import Console

from noted import display, pdf
from noted.models import FormattedRun, Note, NoteContent, ParagraphStyle, ParagraphType


def _note(title: str = "Doc") -> Note:
    """Build a synthetic note.

    Args:
        title: Note title.

    Returns:
        A Note without dates or folder.
    """
    return Note(id=1, identifier="N", title=title, folder=None, created=None, modified=None)


def _heading(text: str, para_type: int) -> FormattedRun:
    """Build a heading run.

    Args:
        text: Heading text, including the trailing newline.
        para_type: A ParagraphType heading constant.

    Returns:
        The formatted run.
    """
    return FormattedRun(
        text=text, length=len(text), paragraph_style=ParagraphStyle(paragraph_type=para_type)
    )


def _content() -> NoteContent:
    """Build note content with a heading, a subheading, a bare URL and an unsafe link.

    Returns:
        The parsed-style note content.
    """
    runs = [
        _heading("Doc\n", ParagraphType.TITLE),
        _heading("Intro\n", ParagraphType.HEADING),
        FormattedRun(text="See https://example.com/page. Done\n", length=34),
        _heading("Doc\n", ParagraphType.SUBHEADING),
        FormattedRun(text="bad\n", length=4, link="javascript:alert(1)"),
    ]
    return NoteContent(
        text="Doc\nIntro\nSee https://example.com/page. Done\nDoc\nbad", formatted_runs=runs
    )


def test_html_headings_get_ids_and_title_reserves_its_anchor() -> None:
    """Test headings carry unique ids and a heading matching the title is renumbered."""
    page = display.get_note_html(_note(), _content())
    assert '<h1 id="doc">Doc</h1>' in page
    assert '<h2 id="intro">Intro</h2>' in page
    assert '<h3 id="doc-1">Doc</h3>' in page


def test_html_toc_only_with_flag() -> None:
    """Test the HTML TOC appears with toc=True and links every heading."""
    assert 'class="toc"' not in display.get_note_html(_note(), _content())
    page = display.get_note_html(_note(), _content(), toc=True)
    assert '<a href="#intro">Intro</a>' in page
    assert '<a href="#doc-1">Doc</a>' in page


def test_html_bare_url_is_linked_without_trailing_period() -> None:
    """Test a bare URL in body text becomes a link that excludes the sentence period."""
    page = display.get_note_html(_note(), _content())
    assert 'See <a href="https://example.com/page">https://example.com/page</a>. Done' in page


def test_html_unsafe_run_link_is_not_linked() -> None:
    """Test a javascript: link on a text run renders as plain text."""
    page = display.get_note_html(_note(), _content())
    assert "javascript:" not in page
    assert "<p>bad</p>" in page


def test_html_quote_bare_url_is_linked() -> None:
    """Test bare URLs inside block quotes are linked and the quote stays escaped."""
    quote = ParagraphStyle(is_quote=True)
    runs = [FormattedRun(text="<q> https://example.com\n", length=24, paragraph_style=quote)]
    page = display.get_note_html(_note(), NoteContent(text="", formatted_runs=runs))
    assert '&lt;q&gt; <a href="https://example.com">https://example.com</a>' in page


def test_markdown_toc_bare_url_and_unsafe_link() -> None:
    """Test Markdown gets a linked TOC, autolinked URLs and no javascript: link."""
    md = display.get_note_markdown(_note(), _content(), toc=True)
    assert md.startswith("# Doc\n\n**Contents**\n\n- [Intro](#intro)\n  - [Doc](#doc-1)\n\n")
    assert "See <https://example.com/page>. Done" in md
    assert "javascript:" not in md
    assert "**Contents**" not in display.get_note_markdown(_note(), _content())


def test_json_toc_lists_headings_with_anchors() -> None:
    """Test JSON output includes the heading list only when asked."""
    data = json.loads(display.get_note_json(_note(), _content(), toc=True))
    assert data["toc"] == [
        {"level": 2, "text": "Intro", "anchor": "intro"},
        {"level": 3, "text": "Doc", "anchor": "doc-1"},
    ]
    assert "toc" not in json.loads(display.get_note_json(_note(), _content()))


def test_text_toc_prefixes_plain_text() -> None:
    """Test plain text output starts with the heading list when asked."""
    text = display.get_note_text(_note(), _content(), toc=True)
    assert text.startswith("Contents\n- Intro\n  - Doc\n\nDoc\nIntro")
    assert display.get_note_text(_note(), _content()) == _content().text


def test_terminal_view_prints_toc() -> None:
    """Test the terminal view lists headings before the body when asked."""
    rec = Console(record=True, width=100, file=io.StringIO(), color_system=None)
    with patch.object(display, "console", rec):
        display.display_note_view(_note(), _content(), toc=True)
    assert "Contents\n- Intro\n  - Doc" in rec.export_text()


def test_toc_skipped_when_note_has_no_headings() -> None:
    """Test --toc adds nothing to a note without headings."""
    content = NoteContent(text="just text")
    assert "Contents" not in display.get_note_markdown(_note(), content, toc=True)
    assert 'class="toc"' not in display.get_note_html(_note(), content, toc=True)
    assert display.get_note_text(_note(), content, toc=True) == "just text"


def _pdf_objects(data: bytes) -> bytes:
    """Return PDF bytes with every compressed stream appended in decompressed form.

    Args:
        data: PDF file content.

    Returns:
        Searchable PDF text.
    """
    text = data
    for match in re.finditer(rb"stream\r?\n", data):
        try:
            text += zlib.decompressobj().decompress(data[match.end() :])
        except zlib.error:
            continue
    return text


@pytest.mark.integration
def test_pdf_has_bookmarks_and_links() -> None:
    """Test the PDF carries heading bookmarks, internal TOC links and the bare URL link."""
    try:
        pdf.load_weasyprint()
    except pdf.PdfUnavailableError as e:
        pytest.skip(f"WeasyPrint native libraries unavailable: {e}")
    objects = _pdf_objects(pdf.render_pdf(display.get_note_html(_note(), _content(), toc=True)))
    assert b"/Outlines" in objects
    assert {b"Doc", b"Intro"} <= set(re.findall(rb"/Title \(([^)]*)\)", objects))
    assert b"/Dest" in objects
    assert b"https://example.com/page" in objects
    assert b"javascript:" not in objects
