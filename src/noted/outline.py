"""Heading anchors, tables of contents and bare-URL detection for note output.

Renderers record each heading in an :class:`Outline` as they emit it, so the anchors
on the headings and the links in the table of contents always agree.
"""

import html
import re
from dataclasses import dataclass, field

URL_PATTERN = re.compile(r"(?:https?://|mailto:)[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?'\""
_CLOSING_BRACKETS = {")": "(", "]": "[", "}": "{"}

TOC_TITLE = "Contents"


@dataclass
class Heading:
    """A heading in a note.

    Attributes:
        level: Heading level, 1 (title) to 3 (subheading).
        text: Heading text.
        anchor: Unique anchor id for linking to the heading.
    """

    level: int
    text: str
    anchor: str


@dataclass
class Outline:
    """Collects a note's headings and hands out unique anchors.

    Attributes:
        headings: Headings in document order.
    """

    headings: list[Heading] = field(default_factory=list)
    _used: set[str] = field(default_factory=set)

    def reserve(self, text: str) -> str:
        """Claim a unique anchor for text without listing it as a heading.

        Used for the note title, which counts toward anchor uniqueness but is not a
        table of contents entry.

        Args:
            text: Text to derive the anchor from.

        Returns:
            The unique anchor.
        """
        base = slugify(text)
        anchor = base
        suffix = 0
        while anchor in self._used:
            suffix += 1
            anchor = f"{base}-{suffix}"
        self._used.add(anchor)
        return anchor

    def add(self, level: int, text: str) -> str:
        """Record a heading and return its unique anchor.

        Args:
            level: Heading level, 1 to 3.
            text: Heading text.

        Returns:
            The heading's anchor.
        """
        anchor = self.reserve(text)
        self.headings.append(Heading(level=level, text=text, anchor=anchor))
        return anchor


def slugify(text: str) -> str:
    """Build a GitHub-style anchor slug.

    GitHub's algorithm is used so Markdown ``#anchor`` links resolve on GitHub and
    most Markdown viewers, which derive heading ids the same way.

    Args:
        text: Heading text.

    Returns:
        Lowercase slug of word characters and hyphens, or ``section`` if empty.
    """
    slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    return slug or "section"


def _trim_url(url: str) -> str:
    """Drop trailing punctuation and unbalanced closing brackets from a matched URL.

    Args:
        url: Candidate URL as matched in running text.

    Returns:
        The URL without sentence punctuation that followed it.
    """
    while url:
        last = url[-1]
        opener = _CLOSING_BRACKETS.get(last)
        unbalanced = opener is not None and url.count(opener) < url.count(last)
        if last not in _TRAILING_PUNCTUATION and not unbalanced:
            break
        url = url[:-1]
    return url


def split_urls(text: str) -> list[tuple[str, bool]]:
    """Split text into plain pieces and bare URLs.

    Args:
        text: Running text.

    Returns:
        ``(piece, is_url)`` pairs that concatenate back to ``text``.
    """
    pieces: list[tuple[str, bool]] = []
    pos = 0
    for match in URL_PATTERN.finditer(text):
        url = _trim_url(match.group())
        scheme_only = url.lower().rstrip("/") in ("http:", "https:", "mailto:")
        if not url or scheme_only:
            continue
        start = match.start()
        if start > pos:
            pieces.append((text[pos:start], False))
        pieces.append((url, True))
        pos = start + len(url)
    if pos < len(text):
        pieces.append((text[pos:], False))
    return pieces


def _toc_indent(heading: Heading, headings: list[Heading]) -> str:
    """Indent for a TOC entry, relative to the shallowest heading level present."""
    top = min(h.level for h in headings)
    return "  " * (heading.level - top)


def markdown_toc(headings: list[Heading]) -> str:
    """Render a Markdown table of contents.

    The title is bold text, not a heading, so it does not shift heading anchors.

    Args:
        headings: Headings in document order.

    Returns:
        Markdown block, or an empty string when there are no headings.
    """
    if not headings:
        return ""
    lines = [f"**{TOC_TITLE}**", ""]
    for h in headings:
        label = h.text.replace("[", "\\[").replace("]", "\\]")
        lines.append(f"{_toc_indent(h, headings)}- [{label}](#{h.anchor})")
    return "\n".join(lines)


def html_toc(headings: list[Heading]) -> str:
    """Render an HTML table of contents.

    Args:
        headings: Headings in document order.

    Returns:
        A ``<nav class="toc">`` block, or an empty string when there are no headings.
    """
    if not headings:
        return ""
    top = min(h.level for h in headings)
    items = "\n".join(
        f'                <li class="toc-depth-{h.level - top}">'
        f'<a href="#{h.anchor}">{html.escape(h.text)}</a></li>'
        for h in headings
    )
    return (
        '            <nav class="toc">\n'
        f'                <p class="toc-title">{TOC_TITLE}</p>\n'
        "                <ul>\n"
        f"{items}\n"
        "                </ul>\n"
        "            </nav>"
    )


def text_toc(headings: list[Heading]) -> str:
    """Render a plain text table of contents.

    Args:
        headings: Headings in document order.

    Returns:
        Indented list, or an empty string when there are no headings.
    """
    if not headings:
        return ""
    lines = [TOC_TITLE]
    lines.extend(f"{_toc_indent(h, headings)}- {h.text}" for h in headings)
    return "\n".join(lines)
