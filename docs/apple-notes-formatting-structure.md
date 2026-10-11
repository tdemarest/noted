# Apple Notes Formatting Structure

> Canonical overview: [apple-notes-storage-reference.md](./apple-notes-storage-reference.md) (body envelope, ParagraphStyle field map, style types). This deep-dive adds the run-level fields (font, weight, underline, link, highlight), checklist and list handling, and rendering notes.

## Hierarchy

```text
NoteStoreProto
  field 2  Document
    field 3  Note
      field 2  note_text
      field 5  attribute_run (repeated)
```

Each `attribute_run` formats a span of `note_text`. Run lengths are in UTF-16 units and add up to the length of the text. Notes splits text into many small runs, so a word may span several runs when its characters differ in style; aggregate runs before rendering.

## AttributeRun fields

| Field | Name | Description |
|-------|------|-------------|
| 1 | length | Span length (UTF-16 units) |
| 2 | paragraph_style | Paragraph-level formatting (below) |
| 3 | font | Font message (family name, size, other attributes) |
| 5 | font_weight | 1 bold, 2 italic, 3 bold + italic |
| 6 | underline | 1 underlined |
| 7 | strikethrough | 1 strikethrough |
| 9 | link | URL string for hyperlinks |
| 12 | attachment_info | 1 identifier, 2 type_uti; see the reference for placeholder matching |
| 13 | timestamp | Per-run timestamp |
| 14 | highlight | 1 highlighted |

Font names (for example `.AppleSystemUIFont`, `Menlo`) can be recovered by scanning the font message for ASCII strings. The link in field 9 is a UTF-8 URL (web, `mailto:`, `tel:`).

## ParagraphStyle fields (run field 2)

The full map is in the reference. Summary:

| Field | Name | Notes |
|-------|------|-------|
| 1 | style | Paragraph type (see below) |
| 2 | alignment | 0 or missing left, 1 center, 2 right, 3 justify |
| 3 | writingDirection | Stored as value + 1; not an indent |
| 4 | indent | Nesting depth for lists and indented text |
| 5 | todo | Message: field 1 uuid, field 2 done |
| 6 | hints | Unused in observed data |
| 7 | startingItemNumber | First number of a numbered list |
| 8 | blockQuoteLevel | 1 means block quote |
| 9 | uuid | 16-byte paragraph id, shared by runs in the same paragraph |

### Style types (field 1)

| Value | Meaning |
|-------|---------|
| none | Body text |
| 0 | Title |
| 1 | Heading |
| 2 | Subheading |
| 4 | Monospaced |
| 100 | Bulleted list |
| 101 | Dashed list |
| 102 | Numbered list |
| 103 | Checklist item |

### Checklists

The done flag is in the nested todo message (style field 5, its field 2):

```text
style.field_5
  field 1: uuid (bytes)
  field 2: done (0 unchecked, 1 checked)
```

```python
if 5 in style:
    todo = decode_fields(style[5][0][1])
    is_checked = 2 in todo and todo[2][0][1] == 1
```

### Indentation

Use style field 4 for the indent depth of both list items and ordinary indented text. Because indentation is stored per run, indenting plain text requires aggregating runs into whole lines first.

### Numbered lists

`startingItemNumber` (field 7) can remain on paragraphs whose list type later changed, so it is not a reliable running index. Count items yourself, resetting when the list type changes.

### Block quotes and code

- Block quotes: `blockQuoteLevel` (field 8) is 1; render with a bar or panel.
- Monospaced (style 4): aggregate consecutive runs into one code block.

## Text styling in code

```python
BOLD, ITALIC, BOLD_ITALIC = 1, 2, 3     # run field 5
UNDERLINE = STRIKETHROUGH = HIGHLIGHT = 1  # run fields 6, 7, 14
bold = weight in (1, 3)
italic = weight in (2, 3)
```

## Attachment placeholders

An attachment is a U+FFFC whose run has `attachment_info` (field 12). A U+FFFC without it is a literal character and is dropped by `_extract_formatting` in `src/noted/protobuf.py`.

## Rendering notes

List items run from one paragraph start to the next newline: print the prefix (bullet, dash or number) only at the start of an item, and aggregate runs to the newline.

## Example

```python
from noted.protobuf import parse_note_data
from noted.models import ParagraphType

content = parse_note_data(note_data, include_formatting=True)

for run in content.formatted_runs:
    if run.text_style and run.text_style.bold:
        print(f"Bold: {run.text}")
    para = run.paragraph_style
    if para and para.paragraph_type == ParagraphType.CHECKLIST:
        print(("[x] " if para.is_checked else "[ ] ") + run.text)
    if para and para.is_quote:
        print(f"> {run.text}")
```
