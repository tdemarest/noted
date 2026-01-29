# Apple Notes Formatting Structure

This document describes the rich text formatting structure in Apple Notes as stored in the `ZICNOTEDATA.ZDATA` column. The data is gzip-compressed protobuf.

## Overview

Apple Notes stores note content as a protobuf with the following hierarchy:

```text
NoteStoreProto (root)
└── field 2: Document
    └── field 3: Note
        ├── field 2: note_text (plain text string)
        └── field 5: attribute_run (repeated) ← Formatting here
```

Each `attribute_run` defines formatting for a span of text. The runs are sequential and their lengths sum to the total text length.

**Important**: Apple Notes splits text into many small runs, often at character boundaries when formatting changes. A single word like "Hello" might be split across multiple runs if different characters have different styles.

## AttributeRun Fields

| Field | Name | Type | Description |
|-------|------|------|-------------|
| 1 | length | int | Number of characters this run applies to |
| 2 | paragraph_style | message | Container for paragraph-level formatting |
| 3 | font | message | Font name and size information |
| 5 | font_weight | int | **1=bold, 2=italic, 3=bold+italic** |
| 6 | underline | int | **1=underlined** |
| 7 | strikethrough | int | **1=strikethrough** |
| 9 | link | string/message | URL for hyperlinks |
| 12 | attachment_info | message | Embedded attachment details |
| 13 | timestamp | int | Creation/modification timestamp |
| 14 | highlight | int | **1=highlighted (yellow background)** |

## Paragraph Style Fields (field 2)

The paragraph style message contains:

| Field | Name | Type | Description |
|-------|------|------|-------------|
| 1 | paragraph_type | int | Type of paragraph (see below) |
| 2 | alignment | int | **1=center, 2=right, 3=justify** (0/missing=left) |
| 3 | indent_level | int | List indentation depth (1, 2, 3...) |
| 4 | text_indent | int | Text indentation level (for non-list content) |
| 5 | checklist_state | message | Contains checked state for checklist items |
| 7 | list_index | int | Position in list (1, 2, 3, 4...) |
| 8 | block_quote | int | **1=block quote** |
| 9 | uuid | bytes | 16-byte paragraph identifier |

### Checklist State (style field 5)

The checklist checked state is stored as a **nested message** in `paragraph_style.field_5`:

```text
paragraph_style.field_5 (message)
└── field 2: is_checked (int) - 0=unchecked, 1=checked
```

Example bytes for checked item: `\x10\x01` (field 2 = 1)
Example bytes for unchecked item: `\x10\x00` (field 2 = 0)

### Indentation

Apple Notes uses two different fields for indentation:

- **style.field_3** (`indent_level`): Used for list item nesting (bullets, numbers, checklists)
- **style.field_4** (`text_indent`): Used for regular text indentation (Tab key indentation)

When parsing, take the maximum of both values to get the effective indentation level.

## Paragraph Types (paragraph_style.field_1)

| Value | Name | Description |
|-------|------|-------------|
| 0 | TITLE | Main title (H1, large bold) |
| 1 | HEADING | Section heading (H2) |
| 2 | SUBHEADING | Subsection heading (H3) |
| 4 | MONOSPACE | Code block (fixed-width font) |
| 100 | BULLET_LIST | Bullet point (•) |
| 101 | DASHED_LIST | Dashed list item (–) |
| 102 | NUMBERED_LIST | Numbered list (1. 2. 3.) |
| 103 | CHECKLIST | Checkbox/todo item (☐/☑) |

## Text Styling

Text can have multiple styles combined:

```python
# AttributeRun field values
BOLD = 1        # field 5
ITALIC = 2      # field 5
BOLD_ITALIC = 3 # field 5
UNDERLINE = 1   # field 6
STRIKETHROUGH = 1  # field 7
HIGHLIGHT = 1   # field 14
```

Examples:
- Bold text: `run.field_5 = 1`
- Italic text: `run.field_5 = 2`
- Bold + Italic: `run.field_5 = 3`
- Underlined: `run.field_6 = 1`
- Strikethrough: `run.field_7 = 1`
- Highlighted: `run.field_14 = 1`

## Text Alignment

Alignment is set in `paragraph_style.field_2`:

| Value | Alignment |
|-------|-----------|
| 0 (or missing) | Left |
| 1 | Center |
| 2 | Right |
| 3 | Justify |

## Lists

Lists use paragraph_type values 100-103 with additional fields:

- **list_index** (field 7): Position in the list (1, 2, 3...)
- **indent_level** (field 3): Nesting depth for sub-items

Example bullet list structure:
```text
• Item 1      → paragraph_type=100, list_index=1, indent_level=0
• Item 2      → paragraph_type=100, list_index=2, indent_level=0
  • Sub-item  → paragraph_type=100, list_index=1, indent_level=1
```

**Note**: The `list_index` field may only be present on the first run of each list item. When rendering numbered lists, it's more reliable to track the count manually.

## Checklists

Checklist items use `paragraph_type=103`. The checked state is in `paragraph_style.field_5`:

```python
# Parsing checked state
if 5 in style:
    checked_data = style[5][0][1]  # bytes
    checked_msg = decode_fields(checked_data)
    if 2 in checked_msg:
        is_checked = checked_msg[2][0][1] == 1
```

## Block Quotes

Block quotes are indicated by `paragraph_style.field_8 = 1`. The quote text is typically rendered with a vertical bar or in a bordered panel.

## Code Blocks

Monospace/code blocks use `paragraph_type = 4`. Consecutive runs with this type should be aggregated into a single code block for rendering.

## Links

Hyperlinks are stored in `AttributeRun.field_9`:
- Simple URL string for web links (e.g., "https://example.com")
- May be a nested message for special link types (mailto:, tel:, etc.)

## Font Information

Font details are in `AttributeRun.field_3` as a message containing:
- Font family name (e.g., ".AppleSystemUIFont", "Menlo")
- Font size
- Other font attributes

The font name can be extracted by splitting on newlines and finding ASCII strings.

## Attachment Placeholders

Embedded attachments (images, PDFs, tables) are represented by:
- U+FFFC (Object Replacement Character) in the text
- `AttachmentInfo` in `AttributeRun.field_12` containing:
  - `field_1`: attachment_identifier (UUID string)
  - `field_2`: type_uti (e.g., "public.jpeg", "com.apple.notes.table")

## Implementation Notes

### Text Indentation Limitation

Apple Notes splits text into many small runs at character boundaries. For example, "Indented text" might become runs like ["In", "den", "ted ", "text"]. This makes rendering text-level indentation (Tab key indentation) complex because:

1. The indent level is stored per-run, not per-line
2. You'd need to aggregate runs into complete lines first
3. Then apply indentation only at line boundaries

Current implementation handles list indentation (which works per-item) but not arbitrary text indentation.

### Run Aggregation

For features like code blocks and block quotes, consecutive runs with the same paragraph type should be aggregated before rendering:

```python
# Aggregate consecutive code block runs
if para_type == MONOSPACE:
    code_text = text
    while next_run.paragraph_type == MONOSPACE:
        code_text += next_run.text
    render_code_block(code_text)
```

### List Item Boundaries

List items span from one `list_index` change to the next, or until a newline. When rendering lists:

1. Detect list type change (bullet → numbered resets counter)
2. Print prefix (•, –, or number) only at item start
3. Aggregate all runs until newline for the item text

## Example: Parsing Formatted Text

```python
from noted.protobuf import parse_note_data
from noted.models import ParagraphType

content = parse_note_data(note_data, include_formatting=True)

for run in content.formatted_runs:
    # Text styling
    if run.text_style:
        if run.text_style.bold:
            print(f"Bold: {run.text}")
        if run.text_style.highlight:
            print(f"Highlighted: {run.text}")

    # Paragraph styling
    if run.paragraph_style:
        para = run.paragraph_style
        if para.paragraph_type == ParagraphType.CHECKLIST:
            checkbox = "☑" if para.is_checked else "☐"
            print(f"{checkbox} {run.text}")
        if para.is_quote:
            print(f"> {run.text}")
```

## References

- Note content location: `ZICNOTEDATA.ZDATA`
- Attachment details: `ZICCLOUDSYNCINGOBJECT` where `ZTYPEUTI` matches attachment type
- Table structure: See `apple-notes-crdt-table-structure.md`
