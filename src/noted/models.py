"""Data models for Apple Notes entities."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Note:
    """Represents an Apple Note.

    Attributes:
        id: The Z_PK primary key from the database.
        identifier: The UUID identifier (ZIDENTIFIER field).
        title: The note title (ZTITLE1 field).
        folder: The folder name, or None if not in a folder.
        created: When the note was created, or None if unknown.
        modified: When the note was last modified, or None if unknown.
    """

    id: int
    identifier: str
    title: str
    folder: str | None
    created: datetime | None
    modified: datetime | None


@dataclass
class NoteSummary:
    """Aggregate statistics about the notes database.

    Attributes:
        total_count: Total number of notes.
        folder_counts: Mapping of folder name to note count.
    """

    total_count: int
    folder_counts: dict[str, int]


@dataclass
class Table:
    """Parsed table from Apple Notes.

    Stores data in a neutral format that can be rendered
    as Rich, markdown, ASCII, or HTML.

    Attributes:
        rows: Number of rows in the table.
        columns: Number of columns in the table.
        cells: Mapping of (row, col) to cell text content.
    """

    rows: int
    columns: int
    cells: dict[tuple[int, int], str]

    def get_cell(self, row: int, col: int) -> str:
        """Get cell content, empty string if not present."""
        return self.cells.get((row, col), "")


@dataclass
class Attachment:
    """Represents an embedded attachment in a note.

    Attributes:
        identifier: Unique identifier (UUID) for the attachment.
        type_uti: Uniform Type Identifier (e.g., 'public.jpeg').
        title: Display name/filename of the attachment, if known.
        table: Parsed table data, if this is a table attachment.
    """

    identifier: str
    type_uti: str
    title: str | None = None
    table: Table | None = None


class ParagraphType:
    """Paragraph type constants from Apple Notes formatting."""

    TITLE = 0  # H1, main title
    HEADING = 1  # H2, section heading
    SUBHEADING = 2  # H3, subsection
    MONOSPACE = 4  # Code block
    BULLET_LIST = 100  # Bullet point (•)
    DASHED_LIST = 101  # Dashed list (–)
    NUMBERED_LIST = 102  # Numbered list (1. 2. 3.)
    CHECKLIST = 103  # Checkbox/todo (☐/☑)


class TextAlignment:
    """Text alignment constants from Apple Notes formatting."""

    LEFT = 0
    CENTER = 1
    RIGHT = 2
    JUSTIFY = 3


@dataclass
class TextStyle:
    """Text styling information for a run of text.

    Attributes:
        bold: True if text is bold.
        italic: True if text is italic.
        underline: True if text is underlined.
        strikethrough: True if text has strikethrough.
        highlight: True if text is highlighted (yellow background).
    """

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    highlight: bool = False


@dataclass
class ParagraphStyle:
    """Paragraph-level formatting information.

    Attributes:
        paragraph_type: Type of paragraph (see ParagraphType constants).
        alignment: Text alignment (see TextAlignment constants).
        indent_level: Indentation depth (0, 1, 2, ...).
        is_quote: True if this is a block quote.
        is_checked: True if this checklist item is checked.
        list_index: Position in list (1, 2, 3, ...) for list items.
    """

    paragraph_type: int | None = None
    alignment: int = 0
    indent_level: int = 0
    is_quote: bool = False
    is_checked: bool = False
    list_index: int | None = None


@dataclass
class FormattedRun:
    """A run of text with consistent formatting.

    Attributes:
        text: The text content of this run.
        length: Number of characters in this run.
        text_style: Character-level styling (bold, italic, etc.).
        paragraph_style: Paragraph-level formatting.
        link: URL if this run is a hyperlink.
    """

    text: str
    length: int
    text_style: TextStyle | None = None
    paragraph_style: ParagraphStyle | None = None
    link: str | None = None


@dataclass
class NoteContent:
    """Parsed content of an Apple Note.

    Attributes:
        text: The plain text content extracted from protobuf.
        attachments: List of embedded attachments found in the note.
        formatted_runs: List of text runs with formatting information.
    """

    text: str
    attachments: list[Attachment] | None = None
    formatted_runs: list[FormattedRun] | None = None
