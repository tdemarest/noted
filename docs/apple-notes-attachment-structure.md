# Apple Notes Attachment Structure

> Canonical overview: [apple-notes-storage-reference.md](./apple-notes-storage-reference.md) (attachment types, file paths, marked-up PDFs, placeholder matching). This deep-dive adds column lists, the exportable-vs-inline split, example SQL and the export conventions used by `noted`.

## Row relationships

An attachment (`Z_ENT = 5`) is one row in `ZICCLOUDSYNCINGOBJECT`. Inline attachments (`Z_ENT = 9`: hashtags, note links, dividers, mentions) share the table but join to their note through `ZNOTE1` instead of `ZNOTE`. See "Attachments on disk" in the reference for the full media path patterns.

Attachment columns:

| Column | Type | Purpose |
|--------|------|---------|
| `Z_PK` | INTEGER | Primary key |
| `ZIDENTIFIER` | TEXT | UUID; matches `attachment_identifier` in the note body |
| `ZTYPEUTI` | TEXT | Uniform Type Identifier (e.g. `public.jpeg`); NULL for unfetched placeholders |
| `ZTITLE` | TEXT | Display name |
| `ZNOTE` | INTEGER | Parent note `Z_PK` |
| `ZMEDIA` | INTEGER | Media row `Z_PK` (NULL for tables, URL cards, marked-up PDFs, drawings) |

Media rows (`Z_ENT = 11`):

| Column | Type | Purpose |
|--------|------|---------|
| `Z_PK` | INTEGER | Referenced by the attachment's `ZMEDIA` |
| `ZIDENTIFIER` | TEXT | Directory name under `Media/` |
| `ZGENERATION1` | TEXT | Generation directory, e.g. `1_<uuid>` |
| `ZFILENAME` | TEXT | File name on disk (empty means no file) |
| `ZFILESIZE` | INTEGER | Often NULL; stat the file instead |

### File sizes

`ZFILESIZE` was unpopulated in every media row checked, so sizes come from the disk:

```python
file_path = find_media_file(media_id, filename)
if file_path:
    size = file_path.stat().st_size
```

Rows without a media row (tables, URL cards, marked-up PDFs, hashtags, links, dividers, mentions) have no file, so a note whose attachments are all of those kinds reports 0 bytes.

## Directory layout

Under `Accounts/<account-id>/`:

```
Media/<media id>/<generation>/<file>     media-backed attachments
Previews/                                rendered thumbnails
FallbackPDFs/<attachment id>/<gen>/FallbackPDF.pdf
Paper/Bundles/<attachment id>.bundle/    PaperKit bundles
```

Example (all ids are placeholders):

```
~/Library/Group Containers/group.com.apple.notes/Accounts/<account-id>/Media/<media-id>/1_<uuid>/example_photo.jpg
```

## UTI handling in noted

The reference maps UTIs to Notes' own attachment types. For export, `noted` splits them by whether a file exists.

Exportable (media row with a file):

| UTI | Kind |
|-----|------|
| `public.jpeg`, `public.png`, `public.heic`, `public.gif`, `com.compuserve.gif`, `public.tiff`, `org.webmproject.webp` | Image |
| `com.adobe.pdf`, `public.pdf` | PDF |
| `com.apple.drawing`, `com.apple.drawing.2` | Drawing (fallback image) |
| Anything else with a media row (office, email, csv, movie, audio) | Generic file |

Not exportable as a file:

| UTI | Reason |
|-----|--------|
| `com.apple.notes.table` | CRDT data in `ZMERGEABLEDATA1`; see [the table doc](./apple-notes-crdt-table-structure.md) |
| `public.url` | URL card; the link is in `ZURLSTRING` (a maps URL means type 7, Map) |
| `com.apple.paper.doc.pdf` | Marked-up PDF; no media row, exported from `FallbackPDFs/` |
| `com.apple.notes.gallery` | Container, no single file |
| `com.apple.notes.inlinetextattachment.hashtag` | Inline hashtag |
| `com.apple.notes.inlinetextattachment.link` | Inline note link (`ZTOKENCONTENTIDENTIFIER` = `applenotes:note/<UUID>?ownerIdentifier=...`) |
| `com.apple.notes.inlinetextattachment.dividerline` | Inline divider |
| `com.apple.notes.inlinetextattachment.mention` | Inline mention |
| (none / NULL) | Type 0, unfetched placeholder |

## Placeholders in the body

Each attachment is a U+FFFC in `note_text`, inside an attribute run with `attachment_info` (field 12: 1 `attachment_identifier`, 2 `type_uti`). A U+FFFC whose run has no `attachment_info` is a literal character, not an attachment, and must be skipped. An identifier with no matching row (for example Evernote-imported tables) is a dangling reference.

```
attribute_run.attachment_info.attachment_identifier -> ZICCLOUDSYNCINGOBJECT.ZIDENTIFIER
    -> ZMEDIA -> media row -> Media/<id>/<generation>/<ZFILENAME>
attribute_run.attachment_info.type_uti              -> repeated UTI, agrees with the row
```

## Example SQL

Attachment metadata for a note:

```sql
SELECT
    att.ZIDENTIFIER AS attachment_id,
    att.ZTYPEUTI    AS type,
    att.ZTITLE      AS title,
    media.ZIDENTIFIER  AS media_id,
    media.ZGENERATION1 AS generation,
    media.ZFILENAME    AS filename
FROM ZICCLOUDSYNCINGOBJECT att
LEFT JOIN ZICCLOUDSYNCINGOBJECT media ON att.ZMEDIA = media.Z_PK
WHERE att.ZNOTE = ?
  AND att.ZTYPEUTI IS NOT NULL;
```

Attachment names for display:

```sql
SELECT ZIDENTIFIER, ZTITLE
FROM ZICCLOUDSYNCINGOBJECT
WHERE ZNOTE = ?
  AND ZIDENTIFIER IS NOT NULL
  AND ZTITLE IS NOT NULL;
```

## Extraction algorithm

```python
def find_media_file(media_identifier, filename):
    """Find a media file under any account directory."""
    accounts = Path.home() / "Library/Group Containers/group.com.apple.notes/Accounts"
    for account_dir in accounts.iterdir():
        media_dir = account_dir / "Media" / media_identifier
        if not media_dir.is_dir():
            continue
        for generation in media_dir.iterdir():
            candidate = generation / filename
            if candidate.exists():
                return candidate
    return None
```

For marked-up PDFs there is no media row; read
`Accounts/<account-id>/FallbackPDFs/<attachment id>/<ZFALLBACKPDFGENERATION>/FallbackPDF.pdf`.

## Export manifest

When exporting attachments, a `manifest.json` is written next to them:

```json
{
  "note_id": 1,
  "note_title": "Example note",
  "exported_at": "2026-01-01T00:00:00.000Z",
  "attachments": [
    {"identifier": "<uuid>", "filename": "example_photo.jpg", "type_uti": "public.jpeg", "exported": true},
    {"identifier": "<uuid>", "filename": null, "type_uti": "com.apple.notes.table",
     "exported": false, "skip_reason": "Rendered inline in note content"}
  ]
}
```

## Filename handling

- Sanitize: replace spaces with underscores, remove `/ \ : * ? " < > |` and control characters, default to `attachment` if nothing remains.
- Duplicates: append a short id suffix (`photo.jpg`, `photo_abc123.jpg`).
