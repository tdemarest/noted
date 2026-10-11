"""Tests for PDF rendering: WeasyPrint loading, offline HTML, and a real render."""

import importlib.resources
import re
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from noted import display, pdf
from noted.cli import app
from noted.models import Note, NoteContent

runner = CliRunner()

GOBJECT_ERROR = "cannot load library 'libgobject-2.0-0': dlopen(libgobject-2.0-0, 0x0002)"

# href/src attributes, CSS @import and url() pointing at a network location.
EXTERNAL_URL = re.compile(
    r"""(?:href|src)\s*=\s*["']?\s*(?:https?:)?//"""
    r"""|@import\s+(?:url\()?\s*["']?\s*(?:https?:)?//"""
    r"""|url\(\s*["']?\s*(?:https?:)?//""",
    re.IGNORECASE,
)


# A font name in a PDF font dictionary, after the six-letter subset prefix.
PDF_FONT_NAME = re.compile(rb"/(?:BaseFont|FontName)\s*/[A-Z]{6}\+([A-Za-z0-9_-]+)")


def _pdf_font_names(data: bytes) -> set[str]:
    """Collect the embedded font names of a PDF, looking inside compressed streams.

    Args:
        data: PDF file content.

    Returns:
        Font names with the subset prefix removed, e.g. ``Roboto-Bold``.
    """
    text = data
    for match in re.finditer(rb"stream\r?\n", data):
        try:
            text += zlib.decompressobj().decompress(data[match.end() :])
        except zlib.error:
            continue
    return {name.decode() for name in PDF_FONT_NAME.findall(text)}


def _note() -> Note:
    """Build a synthetic note.

    Returns:
        A Note with fixed metadata.
    """
    return Note(
        id=7,
        identifier="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        title="Sample Note",
        folder="Sample Folder",
        created=datetime(2025, 1, 15, 10, 30, tzinfo=UTC),
        modified=datetime(2025, 1, 28, 14, 45, tzinfo=UTC),
    )


def _flat(text: str) -> str:
    """Collapse whitespace so Rich line wrapping does not split phrases.

    Args:
        text: Console output.

    Returns:
        The text with every whitespace run replaced by one space.
    """
    return " ".join(text.split())


def _fail_with_banner() -> ModuleType:
    """Stand-in for the WeasyPrint import that fails like a missing dylib.

    Raises:
        OSError: Always, after printing a banner like WeasyPrint's.
    """
    sys.stdout.write("WeasyPrint could not import some external libraries.\n")
    raise OSError(GOBJECT_ERROR)


def test_load_weasyprint_raises_actionable_error_on_oserror(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dlopen failure becomes PdfUnavailableError naming both fixes, without the banner."""
    with (
        patch("noted.pdf._import_weasyprint", side_effect=_fail_with_banner),
        pytest.raises(pdf.PdfUnavailableError) as excinfo,
    ):
        pdf.load_weasyprint()
    message = str(excinfo.value)
    assert "brew install pango" in message
    assert "DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib" in message
    assert isinstance(excinfo.value.__cause__, OSError)
    assert "WeasyPrint could not import" not in capsys.readouterr().out


def test_view_pdf_fails_loudly_when_weasyprint_cannot_load() -> None:
    """``view --pdf --export`` exits 1 with the install hint before touching the database."""
    with (
        patch("noted.pdf._import_weasyprint", side_effect=OSError(GOBJECT_ERROR)),
        patch("noted.cli.db.get_connection") as get_connection,
    ):
        result = runner.invoke(app, ["view", "7", "--pdf", "--export"])
    assert result.exit_code == 1
    output = _flat(result.output)
    assert "brew install pango" in output
    assert "DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib" in output
    get_connection.assert_not_called()


def test_homebrew_search_path_is_set_during_import_and_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On macOS the Homebrew lib dir is searched during the import only, after the user's."""
    monkeypatch.setattr(pdf.sys, "platform", "darwin")
    monkeypatch.setenv("DYLD_FALLBACK_LIBRARY_PATH", "/custom/lib")
    seen: list[str] = []

    def fake_import() -> ModuleType:
        """Record the search path in effect at import time.

        Returns:
            A placeholder module.
        """
        seen.append(pdf.os.environ["DYLD_FALLBACK_LIBRARY_PATH"])
        return ModuleType("weasyprint")

    with (
        patch("noted.pdf.homebrew_lib_dirs", return_value=[tmp_path]),
        patch("noted.pdf._import_weasyprint", side_effect=fake_import),
    ):
        pdf.load_weasyprint()
    parts = seen[0].split(":")
    assert parts[0] == "/custom/lib"
    assert parts[1] == str(tmp_path)
    assert "/usr/lib" in parts
    assert pdf.os.environ["DYLD_FALLBACK_LIBRARY_PATH"] == "/custom/lib"


def test_homebrew_search_path_untouched_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Other platforms import WeasyPrint with the environment unchanged."""
    monkeypatch.setattr(pdf.sys, "platform", "linux")
    monkeypatch.delenv("DYLD_FALLBACK_LIBRARY_PATH", raising=False)
    fake = MagicMock(return_value=ModuleType("weasyprint"))
    with patch("noted.pdf._import_weasyprint", fake):
        pdf.load_weasyprint()
    assert "DYLD_FALLBACK_LIBRARY_PATH" not in pdf.os.environ


def test_note_html_references_no_external_urls() -> None:
    """The HTML used for PDF output needs no network (no web fonts or remote CSS)."""
    html_doc = display.get_note_html(_note(), NoteContent(text="Body text"))
    assert EXTERNAL_URL.search(html_doc) is None, EXTERNAL_URL.search(html_doc)
    assert "fonts.googleapis" not in html_doc


def test_font_face_css_references_bundled_fonts() -> None:
    """Every @font-face rule points at a font file shipped in the package, and nothing remote."""
    css = pdf.font_face_css()
    fonts = importlib.resources.files("noted").joinpath("fonts")
    assert len(pdf.FONT_FACES) == css.count("@font-face")
    for name, weight, style in pdf.FONT_FACES:
        assert f"url('{name}')" in css
        assert f"font-weight: {weight}; font-style: {style};" in css
        assert fonts.joinpath(name).is_file(), name
    assert fonts.joinpath("OFL.txt").is_file()
    assert EXTERNAL_URL.search(css) is None
    assert "file:" not in css


def test_note_html_prefers_roboto_without_local_paths() -> None:
    """The shared HTML names Roboto first but carries no @font-face or file path."""
    html_doc = display.get_note_html(_note(), NoteContent(text="Body text"))
    assert "font-family: 'Roboto', -apple-system," in html_doc
    assert "@font-face" not in html_doc
    assert "file:" not in html_doc


@pytest.mark.integration
def test_render_pdf_embeds_bundled_roboto() -> None:
    """A rendered note embeds the bundled Roboto faces: regular, medium heading, bold footer."""
    try:
        pdf.load_weasyprint()
    except pdf.PdfUnavailableError as e:
        pytest.skip(f"WeasyPrint native libraries unavailable: {e}")
    html_doc = display.get_note_html(_note(), NoteContent(text="Hello\nSecond line"))
    names = _pdf_font_names(pdf.render_pdf(html_doc))
    assert {"Roboto", "Roboto-Medium", "Roboto-Bold"} <= names, names


@pytest.mark.integration
def test_render_pdf_writes_real_pdf(tmp_path: Path) -> None:
    """Render a synthetic note to a real PDF with the installed WeasyPrint."""
    try:
        pdf.load_weasyprint()
    except pdf.PdfUnavailableError as e:
        pytest.skip(f"WeasyPrint native libraries unavailable: {e}")
    html_doc = display.get_note_html(_note(), NoteContent(text="Hello\nSecond line"))
    out = tmp_path / "note.pdf"
    out.write_bytes(pdf.render_pdf(html_doc))
    assert out.read_bytes().startswith(b"%PDF")
