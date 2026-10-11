"""Tests for noted.outline: anchors, bare-URL splitting and TOC rendering."""

import pytest

from noted.outline import (
    Heading,
    Outline,
    html_toc,
    markdown_toc,
    slugify,
    split_urls,
    text_toc,
)


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Getting Started", "getting-started"),
        ("  Q&A: 2026 plan!  ", "qa-2026-plan"),
        ("Café notes", "café-notes"),
        ("snake_case-and-dash", "snake_case-and-dash"),
        ("!!!", "section"),
    ],
)
def test_slugify(text: str, slug: str) -> None:
    """Test slugs follow GitHub's lowercase, strip-punctuation, hyphenate rules."""
    assert slugify(text) == slug


def test_outline_dedupes_anchors_after_reserved_title() -> None:
    """Test repeated headings and a heading matching the title get numbered anchors."""
    outline = Outline()
    assert outline.reserve("Plan") == "plan"
    assert outline.add(2, "Plan") == "plan-1"
    assert outline.add(2, "Plan") == "plan-2"
    assert outline.add(3, "Other") == "other"
    assert [h.anchor for h in outline.headings] == ["plan-1", "plan-2", "other"]


def test_split_urls_finds_urls_and_round_trips() -> None:
    """Test URLs are split out and the pieces concatenate back to the input."""
    text = "Docs at https://example.com/x?a=1&b=2 and mailto:someone@example.com today"
    pieces = split_urls(text)
    assert "".join(p for p, _ in pieces) == text
    assert [p for p, is_url in pieces if is_url] == [
        "https://example.com/x?a=1&b=2",
        "mailto:someone@example.com",
    ]


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("See https://example.com.", "https://example.com"),
        ("(https://example.com/page)", "https://example.com/page"),
        ("https://en.example.org/wiki/A_(b), next", "https://en.example.org/wiki/A_(b)"),
        ('"https://example.com/q"', "https://example.com/q"),
    ],
)
def test_split_urls_trims_trailing_punctuation(text: str, url: str) -> None:
    """Test sentence punctuation and unbalanced brackets are left out of the URL."""
    assert [p for p, is_url in split_urls(text) if is_url] == [url]


@pytest.mark.parametrize("text", ["plain text", "http:// alone", "javascript:alert(1)", ""])
def test_split_urls_ignores_non_urls(text: str) -> None:
    """Test text without a usable http(s) or mailto URL yields no URL pieces."""
    assert not any(is_url for _, is_url in split_urls(text))


HEADINGS = [
    Heading(level=2, text="Intro [draft]", anchor="intro-draft"),
    Heading(level=3, text="A <b> & c", anchor="a-b--c"),
]


def test_markdown_toc_links_and_nests() -> None:
    """Test the Markdown TOC links each anchor, nests by level and escapes brackets."""
    assert markdown_toc(HEADINGS) == (
        "**Contents**\n\n- [Intro \\[draft\\]](#intro-draft)\n  - [A <b> & c](#a-b--c)"
    )


def test_html_toc_escapes_and_nests() -> None:
    """Test the HTML TOC escapes heading text and marks relative depth."""
    out = html_toc(HEADINGS)
    assert '<li class="toc-depth-0"><a href="#intro-draft">Intro [draft]</a></li>' in out
    assert '<li class="toc-depth-1"><a href="#a-b--c">A &lt;b&gt; &amp; c</a></li>' in out


def test_text_toc_indents() -> None:
    """Test the plain text TOC indents by level."""
    assert text_toc(HEADINGS) == "Contents\n- Intro [draft]\n  - A <b> & c"


def test_tocs_are_empty_without_headings() -> None:
    """Test no TOC is produced for a note without headings."""
    assert markdown_toc([]) == html_toc([]) == text_toc([]) == ""
