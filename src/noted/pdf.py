"""PDF rendering through WeasyPrint, with macOS Homebrew library discovery.

WeasyPrint loads Pango, HarfBuzz, fontconfig and GObject at import time via cffi
``ffi.dlopen`` with bare library names. On macOS, dyld does not search Homebrew's
``lib`` directory for bare names, so a uv-managed Python fails to import WeasyPrint
unless ``DYLD_FALLBACK_LIBRARY_PATH`` was set before the process started.

cffi falls back to ``ctypes.util.find_library`` when a bare-name dlopen fails, and
that fallback is pure Python: it reads ``DYLD_FALLBACK_LIBRARY_PATH`` from
``os.environ`` at call time and returns an absolute path, which dyld then loads.
So setting the variable in ``os.environ`` just for the duration of the import is
enough, and it is restored afterwards so child processes are unaffected.
"""

import contextlib
import importlib
import importlib.resources
import io
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

from loguru import logger

_DYLD_VAR = "DYLD_FALLBACK_LIBRARY_PATH"

# ctypes' default dyld fallback directories; kept when we set the variable so that
# libraries found there before are still found.
_DEFAULT_DYLD_FALLBACK = (str(Path.home() / "lib"), "/usr/local/lib", "/usr/lib")

PDF_UNAVAILABLE_HELP = (
    "PDF export needs WeasyPrint's native libraries (Pango, HarfBuzz, fontconfig, GObject), "
    "which could not be loaded. On macOS install them with `brew install pango`; if they are "
    "installed somewhere unusual, run with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` "
    "(or your Homebrew prefix's lib directory)."
)


# Roboto faces bundled in ``noted/fonts`` (static TTFs from googlefonts/roboto-3-classic
# v3.016, SIL OFL 1.1; see ``fonts/OFL.txt``), as (file name, CSS weight, CSS style).
# Only the weights and styles the note stylesheet uses are shipped: 400 body text,
# 500 headings, 700 ``<strong>``, plus italics for ``<em>``.
FONT_FAMILY = "Roboto"
FONT_FACES: tuple[tuple[str, int, str], ...] = (
    ("Roboto-Regular.ttf", 400, "normal"),
    ("Roboto-Italic.ttf", 400, "italic"),
    ("Roboto-Medium.ttf", 500, "normal"),
    ("Roboto-Bold.ttf", 700, "normal"),
    ("Roboto-BoldItalic.ttf", 700, "italic"),
)


class PdfUnavailableError(RuntimeError):
    """Raised when WeasyPrint or its native libraries cannot be loaded."""


def homebrew_lib_dirs() -> list[Path]:
    """Return existing Homebrew library directories, most specific first.

    Returns:
        ``$HOMEBREW_PREFIX/lib``, ``/opt/homebrew/lib`` and ``/usr/local/lib``, in that
        order, keeping only directories that exist and dropping duplicates.
    """
    candidates: list[Path] = []
    prefix = os.environ.get("HOMEBREW_PREFIX")
    if prefix:
        candidates.append(Path(prefix) / "lib")
    candidates += [Path("/opt/homebrew/lib"), Path("/usr/local/lib")]
    dirs: list[Path] = []
    for path in candidates:
        if path.is_dir() and path not in dirs:
            dirs.append(path)
    return dirs


@contextlib.contextmanager
def _homebrew_library_search() -> Iterator[None]:
    """Temporarily add Homebrew lib dirs to ``DYLD_FALLBACK_LIBRARY_PATH`` on macOS.

    A no-op on other platforms or when no Homebrew lib directory exists. Any value
    the user already set is searched first. The original value is restored on exit.

    Yields:
        None, while the extended search path is in effect.
    """
    brew_dirs = homebrew_lib_dirs() if sys.platform == "darwin" else []
    if not brew_dirs:
        yield
        return
    original = os.environ.get(_DYLD_VAR)
    parts = [p for p in (original or "").split(":") if p]
    for entry in [*(str(d) for d in brew_dirs), *_DEFAULT_DYLD_FALLBACK]:
        if entry not in parts:
            parts.append(entry)
    os.environ[_DYLD_VAR] = ":".join(parts)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(_DYLD_VAR, None)
        else:
            os.environ[_DYLD_VAR] = original


def _import_weasyprint() -> ModuleType:
    """Import and return the ``weasyprint`` module (a seam for tests).

    Returns:
        The ``weasyprint`` module.
    """
    return importlib.import_module("weasyprint")


def load_weasyprint() -> ModuleType:
    """Import WeasyPrint, finding Homebrew's native libraries on macOS.

    The import is lazy because WeasyPrint is heavy and loads native libraries that
    only ``--pdf`` needs.

    Returns:
        The imported ``weasyprint`` module.

    Raises:
        PdfUnavailableError: If WeasyPrint or one of its native libraries cannot load.
    """
    banner = io.StringIO()
    try:
        # WeasyPrint prints an install banner to stdout when a library is missing;
        # capture it so the user sees only our actionable message.
        with _homebrew_library_search(), contextlib.redirect_stdout(banner):
            return _import_weasyprint()
    except (OSError, ImportError) as e:
        logger.debug("WeasyPrint import failed: {}{}", e, banner.getvalue())
        raise PdfUnavailableError(PDF_UNAVAILABLE_HELP) from e


def font_face_css() -> str:
    """Build the ``@font-face`` rules for the bundled Roboto faces.

    The ``src`` URLs are bare file names, resolved against the packaged fonts
    directory by the ``base_url`` that :func:`render_pdf` gives the stylesheet. The
    rules are applied only to PDF output, so the HTML export never carries a
    machine-specific path.

    Returns:
        CSS text with one ``@font-face`` rule per entry in :data:`FONT_FACES`.
    """
    return "\n".join(
        f"@font-face {{ font-family: '{FONT_FAMILY}'; src: url('{name}'); "
        f"font-weight: {weight}; font-style: {style}; }}"
        for name, weight, style in FONT_FACES
    )


def render_pdf(html: str) -> bytes:
    """Render an HTML document to PDF bytes, with the bundled Roboto fonts.

    Args:
        html: A complete HTML document. It should reference no network resources.

    Returns:
        The PDF file content.

    Raises:
        PdfUnavailableError: If WeasyPrint cannot be loaded.
        RuntimeError: If WeasyPrint returns no output.
    """
    weasyprint = load_weasyprint()
    fonts = importlib.resources.files("noted").joinpath("fonts")
    with importlib.resources.as_file(fonts) as fonts_dir:
        font_config = weasyprint.text.fonts.FontConfiguration()
        stylesheet = weasyprint.CSS(
            string=font_face_css(),
            base_url=f"{fonts_dir.as_uri()}/",
            font_config=font_config,
        )
        result = weasyprint.HTML(string=html).write_pdf(
            stylesheets=[stylesheet], font_config=font_config
        )
    if result is None:
        raise RuntimeError("PDF generation failed")
    return result
