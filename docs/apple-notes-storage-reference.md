# How Apple Notes Stores Your Notes

> Reference. Source: research write-up dated 2026-10-10 (originally `~/Downloads/How Apple Notes Stores Your Notes.md`), plus the reader recipe and consistency notes at the end.

Oct 10, 2026 · @Timothy Demarest

Related docs (deep-dives that complement this reference; where they disagree, this document wins):

- [Database fields](./apple-notes-database-fields.md) - column lists, smart folder queries, hashtags, sharing, encryption, example SQL
- [Attachment structure](./apple-notes-attachment-structure.md) - attachment and media columns, exportable UTIs, export conventions
- [CRDT table structure](./apple-notes-crdt-table-structure.md) - protobuf layout and decoding steps for tables
- [Formatting structure](./apple-notes-formatting-structure.md) - attribute run fields, lists, checklists, rendering notes
- [Timestamp structure](./apple-notes-timestamp-structure.md) - date columns per entity, conversion code

## Summary

All 14 questions are answered from evidence, including live tests on an iPhone and on this Mac. Attachment and folder types are confirmed from decompiled Notes code. Reading a library needs no further reverse engineering: bodies and tables decode with the public protobuf definitions, and every file path follows a fixed pattern.

A note row points to its body; each U+FFFC in the text carries an attachment identifier; the attachment's UTI decides whether content sits in a media file, in the database as CRDT data, or in a paper bundle. Files live under `Accounts/<account-id>/` in the Notes group container.

Two surprises worth knowing: 386 hidden records are stubs of notes that no longer exist in iCloud, and 22 notes imported from Evernote reference 326 tables that were never created, so those tables show blank.

## Background: the database layout

Notes keeps everything in one Core Data SQLite file, `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`, plus media files beside it. The schema ships inside macOS as `NotesShared.framework/Resources/NoteData.mom`. REA decoded that compiled model (evidence `ev_3062bff9…a8a8`) into 22 entities.

Most entities inherit from `ICCloudSyncingObject`, so Core Data stores them in one shared table, `ZICCLOUDSYNCINGOBJECT`. The `Z_ENT` column says which kind of object each row is. Attributes that two subentities both define get a numeric suffix (`ZTYPEUTI` for attachments, `ZTYPEUTI1` for inline attachments).

| Z\_ENT | Entity | Table | Rows in this library | Holds |
| --- | --- | --- | --- | --- |
| 12 | ICNote | ZICCLOUDSYNCINGOBJECT | 2,287 | Title, snippet, dates, flags (pinned, locked, Quick Note, paper style) |
| 5 | ICAttachment | ZICCLOUDSYNCINGOBJECT | 3,938 | One row per embedded object; kind set by `ZTYPEUTI` |
| 11 | ICMedia | ZICCLOUDSYNCINGOBJECT | 3,525 | Pointer to a file on disk (filename, generation) |
| 6 | ICAttachmentPreviewImage | ZICCLOUDSYNCINGOBJECT | 9,275 | Rendered thumbnails per size and appearance |
| 9 | ICInlineAttachment | ZICCLOUDSYNCINGOBJECT | 57 | Hashtags, note links, divider lines inside the text |
| 15 | ICFolder | ZICCLOUDSYNCINGOBJECT | 141 | Regular, smart and system folders |
| 8 | ICHashtag | ZICCLOUDSYNCINGOBJECT | 10 | Tag registry |
| 14 | ICAccount | ZICCLOUDSYNCINGOBJECT | 1 | iCloud account |
| 19 | ICNoteData | ZICNOTEDATA | 2,287 | The note body blob |
| 2, 1, 22 | ICCloudState, ICAssetSignature, ICServerChangeToken | own tables |  | iCloud sync bookkeeping |
| 16, 20 | ICInvitation, ICNoteParticipant | own tables |  | Sharing |
| 18 | ICAttachmentLocation | ZICLOCATION |  | Where an attachment was created |

An attachment's kind is computed from its `ZTYPEUTI` by Notes' own `-[ICAttachment attachmentType]`. Running that code on each UTI string in an in-memory store gave this mapping.

| Type | Name | UTIs | Model class | Count here |
| --- | --- | --- | --- | --- |
| 2 | Generic file | anything not listed below | ICAttachmentGenericModel | \~150 |
| 3 | Image | public.jpeg, png, heic, tiff, gif, webp | ICAttachmentImageModel | \~1,900 |
| 4 | Audio | public.mp3, com.apple.m4a-audio | ICAttachmentAudioModel | 3 |
| 5 | Movie | public.mpeg-4, com.apple.quicktime-movie | ICAttachmentMovieModel | 12 |
| 6 | PDF | com.adobe.pdf | ICAttachmentPDFModel | 1,448 |
| 8 | URL card | public.url | ICAttachmentWebModel | 36 |
| 9 | Legacy sketch | com.apple.notes.sketch | ICAttachmentDrawingModel | 0 |
| 10 | Drawing | com.apple.drawing, com.apple.drawing.2 | ICAttachmentInlineDrawingModel | 1 |
| 11 | Scan gallery (old) | com.apple.notes.gallery | ICAttachmentGalleryModel | 0 |
| 12 | Table | com.apple.notes.table | ICAttachmentTableModel | 331 |
| 13 | Handwriting paper | com.apple.paper | ICAttachmentSystemPaperModel | 0 |
| 14 | Marked-up PDF | com.apple.paper.doc.pdf | ICAttachmentPaperDocumentModel | 19 |
| 15 | Scan (new) | com.apple.paper.doc.scan | ICAttachmentPaperDocumentModel | 0 |

Decompiling `-[ICAttachment attachmentType]` in REA shows the complete rule, including the types no UTI produced:

```
attachmentType
  isUnsupported                     -> 1  (row needs a newer Notes version, or its UTI is not allowed in a locked note)
  typeUTI is nil                    -> 0  (unfetched placeholder)
  attachmentTypeFromTypeUTI         -> 3 image, 4 audio, 5 movie, 6 PDF, 10 drawing, 9 sketch,
                                       11 gallery, 12 table, 13 paper, 14 paper.doc / paper.doc.pdf, 15 paper.doc.scan
  else if isURL: URL.ic_isMapURL    -> 7 Map, otherwise 8 URL
  else                              -> 2 generic file
```

So Map (7) is a URL card whose link is a maps URL. Folders use `ZFOLDERTYPE` (0, 1, 2) and notes use flags rather than a type column; both are covered under Enums and Structure.

## Note bodies

### Q1. Does the public notestore.proto decode them?

Yes. All 1,897 gzip bodies and the 1 zlib body parse against the open-source [notestore.proto](https://github.com/threeplanetssoftware/apple_cloud_notes_parser/blob/master/proto/notestore.proto) with no wire-type errors. In every note, the attribute-run lengths add up exactly to the UTF-16 length of the text, so no further reverse engineering is needed to read bodies.

```
ZICNOTEDATA.ZDATA  --gunzip-->  NoteStoreProto
  field 2  Document
    field 2  version (varint)
    field 3  Note
      field 2  note_text       the plain text, U+FFFC where an attachment sits
      field 5  attribute_run   repeated: length, paragraph style, font, links, attachment_info
```

A few fields are present that the public proto does not model. None block decoding.

| Message | Field | Seen | Meaning |
| --- | --- | --- | --- |
| Note (`topotext.String`) | 3 (repeated) | 359,440 | `topotext.Substring`: the CRDT pieces of text with their edit ids, confirmed from Apple's serializer |
| Note (`topotext.String`) | 4 | once per note | A single message; its shape (UUID plus replica entries) fits `topotext.VectorTimestamp` |
| Note (`topotext.String`) | 6 (repeated) |  | `topotext.Attachment`, written by the serializer but absent from this data |
| ParagraphStyle | 3 | 258,991 | `writingDirection`, stored as value + 1; always 1 here (left to right). Absent means natural direction |
| ParagraphStyle | 6 | 0 | `hints`; never used in this library |
| ParagraphStyle | 7 | 1,651 | `startingItemNumber`: the first number of a numbered list. Kept on paragraphs whose list type later changed |
| ParagraphStyle | 9 | 172,368 | `uuid`: 16-byte paragraph id, shared by every run in the same paragraph |
| AttributeRun | 13 |  | Per-run timestamp (10-digit epoch-like value) |

Apple builds these with protobuf-lite, which keeps no field names, so the ParagraphStyle names come from a round trip: setting each property of `ICTTMutableParagraphStyle` and calling `-serialize` showed which field changed. The full map is 1 style, 2 alignment, 3 writingDirection, 4 indent, 5 todo, 6 hints, 7 startingItemNumber, 8 blockQuoteLevel, 9 uuid.

Paragraph styles in this library (names from the parser's source, since the proto has no enum):

| style\_type | Meaning | Runs |
| --- | --- | --- |
| none | Body text | 172,661 |
| 100 | Bulleted list | 73,877 |
| 1 | Heading | 9,655 |
| 103 | Checklist item | 6,061 |
| 2 | Subheading | 5,303 |
| 0 | Title | 4,947 |
| 4 | Monospaced | 3,735 |
| 102 | Numbered list | 3,126 |
| 101 | Dashed list | 446 |

Checklist runs (6,061) match the 6,061 checklist messages exactly; each carries its own UUID and done flag.

### Q2. How an attachment placeholder finds its row

Each U+FFFC sits in an attribute run whose `attachment_info` (field 12) holds `attachment_identifier` and `type_uti`. The identifier is the attachment's `ZIDENTIFIER`; the row joins to its note through `ZNOTE` (attachments) or `ZNOTE1` (inline attachments). `type_uti` is repeated in the run and agrees with the row in 3,940 of 3,940 matches.

- 4,267 runs carry `attachment_info`; 3,940 match a row of the same note.
- 326 of the 327 misses are tables, all in 22 notes that have no table rows at all. The database has 331 table rows but 657 table placeholders in bodies; see the follow-up below.
- 4,280 U+FFFC characters versus 4,267 runs: 13 extra in 7 notes. These are literal U+FFFC characters typed into the text, not attachments: each sits in a run with only a length and paragraph style (one also has an http link), alone on its line or in groups of up to three. The notes date from 2018 to 2022, so this is not the Evernote import; the pattern fits rich text pasted from a web page or email whose images did not come across. Notes stores them as plain characters, and a reader should skip a U+FFFC whose run has no attachment\_info.

#### Follow-up: the 326 tables with no rows

The table rows never reached this Mac; they were not deleted here. The split is all-or-nothing by note: 22 notes are missing every table they reference, and the other 111 notes with tables have every row.

|  | 22 notes missing tables | 111 notes with tables |
| --- | --- | --- |
| Created | 2008 to 2018 | Mostly 2018 to 2026 |
| Last modified | 2009 to 2018, one in 2022 | Mostly 2018 to 2026 |
| Missing table rows | 326 (1 to 83 per note) | 0 |
| Other attachments present | 211 of 211 | all |
| Placeholder timestamp in run | none of 326 | 54 of 331 |
| Synced, no local changes pending | yes | yes |

Core Data's change history, which starts when this library was set up on 2026-03-12, rules out local deletion. All 340 attachment deletions in it belong to purged notes (21) or single removals in other notes (5); none touch these 22. Their notes and 211 other attachments arrived together on 2026-03-13, but no table row ever did. No missing ID is shared between notes, and no table row is orphaned.

**Cause, confirmed by the library's owner:** these 22 notes were exported from Evernote and imported into Notes. The import wrote table placeholders into the note bodies but never created the table records, so the references dangle. Opening one on the Mac shows the tables as blank, which matches Notes' code: a placeholder with no row only logs `Attachment not found in note` (`-[ICNote rangeForAttachment:]`, REA `ev_1931e0e1…`). The table contents are not recoverable from this library; the original Evernote export is the only source.

### Q3. The three unusual bodies

Two are the two locked notes. Their body is an NSKeyedArchiver plist with root class `ICCryptoEncryptionObject` (keys `metadata`, `unauthenticatedMetadata`, `wrappedEncryptionKey`, `encryptedData`). They are the only rows with `ZCRYPTOINITIALIZATIONVECTOR` and `ZCRYPTOTAG` set; the text cannot be read without the password.

The third is zlib instead of gzip. It inflates to the same protobuf structure (28 runs, 13 attachments) and was last modified in 2019, so it is most likely written by an older Notes version.

### Q4. The 387 empty bodies

386 are leftover stubs for notes that no longer exist in iCloud. All have `ZNEEDSINITIALFETCHFROMCLOUD = 1`, no server record data, no folder, no dates and no attachments. By contrast, every note with a body has a server record and the flag at 0. These are the same rows as the 386 folderless notes under Enums.

The remaining one is a local-only note (`ZINCLOUD = 0`) in a regular folder with one attachment. Opening a placeholder in Notes confirmed this on 2026-10-10. A link to one stub showed "Note Unavailable: the note was deleted, exists on a different device or account, or is not shared with you." Within a minute, Notes moved that stub to Recently Deleted and set `ZMARKEDFORDELETION = 1`; no other stub changed. So Notes asked iCloud for the note, found nothing, and cleaned up. The stubs are invisible because they have no folder, and Notes only removes one when something asks for it.

## Tables and other mergeable data

### Q5. How a table is stored

A table lives in `ZMERGEABLEDATA1` on its attachment row, gzip-compressed, and decodes with the public `MergableDataProto` (322 of 322 tables, no wire-type errors). The other 9 table rows have no data yet. The three mergeable columns belong to different entities:

| Column | Used by | Rows |
| --- | --- | --- |
| `ZMERGEABLEDATA` | Account data (Z\_ENT 4) | 1 |
| `ZMERGEABLEDATA1` | Attachments: tables | 322 |
| `ZMERGEABLEDATA2` | Folders | 19 |

Inside, a table is a CRDT object graph rather than a grid. One flat list of objects is addressed by index, with shared key and type name tables:

```
MergableDataProto > field 2 MergableDataObject > field 3 data
  field 3  entries[]   objects, addressed by index (ObjectID.object_index)
  field 4  keys[]      identity, crRows, crColumns, cellColumns, crTableColumnDirection, UUIDIndex, self
  field 5  types[]     com.apple.notes.ICTable, com.apple.CRDT.NSUUID, com.apple.CRDT.NSString, ...
  field 6  uuids[]     every row and column id, as 16 raw bytes

UUID object      = custom map { UUIDIndex -> n }          meaning uuids[n]
ICTable          = custom map { crRows, crColumns, cellColumns, crTableColumnDirection, identity }

crRows / crColumns -> OrderedSet
  ordering.array.attachment[i].uuid   position i in display order (a "slot" id)
  ordering.contents { slot -> id }    maps each slot to the row or column id that cells use
cellColumns -> Dictionary { column id -> Dictionary { row id -> cell } }
cell             = entry with a nested Note: note_text + attribute_run, same as a body
crTableColumnDirection -> NSString "CRTableColumnDirectionLeftToRight"
```

So each cell is a small note with its own formatting. The most common sizes here are 1 row by 2 columns (57 tables), 1 by 1 (47) and 1 by 3 (28).

To read a cell at display row r and column c: take slot r from `crRows.ordering.array`, map it through `ordering.contents` to a row id, do the same for the column, then look up `cellColumns[column id][row id]`. Cells never use slot ids directly. The extra step lets rows and columns move on one device while another edits cells, without rewriting the cells.

Traced on all 324 tables in this library on 2026-10-10:

| Check | Result |
| --- | --- |
| Tables resolved | 324 of 324 |
| Cells placed on a row and column | 6,674, none orphaned, none duplicated |
| Grid positions with no cell entry | 574 of 7,248 (never typed in; read as blank) |
| Cells present but blank | 592 |
| Tables with every position filled | 277; 47 have gaps |
| Slot mappings for removed rows or columns | 84, never referenced by a cell |
| Column direction | Left to right in all 324 |
| Largest table | 104 rows by 7 columns |

An exporter must treat a missing cell entry as an empty cell and skip mappings whose slot is no longer in the ordering array.

## Attachments on disk

### Q6. From attachment row to file

Every file-backed attachment resolves with one join and a fixed path pattern: 3,519 of 3,525 media rows (99.8%) point at a file that exists. The 6 misses have an empty `ZFILENAME`.

```
Attachment (Z_ENT 5).ZMEDIA  ->  Media (Z_ENT 11).Z_PK
Accounts/<account-id>/Media/<media.ZIDENTIFIER>/<media.ZGENERATION1>/<media.ZFILENAME>
```

`ZGENERATION1` is a ready-made directory name such as `1_<uuid>`. PDFs, images, office files and email all follow this pattern; `file` confirmed the type matches the UTI on a random 50. RTFD and folder attachments keep their own subtree inside the generation directory.

The other file kinds use the attachment's own `ZIDENTIFIER`:

| What | Path under Accounts/\<account-id>/ | Matched |
| --- | --- | --- |
| Media file | `Media/<media id>/<ZGENERATION1>/<ZFILENAME>` | 3,519 of 3,525 |
| Preview image | `Previews/<attachment id>-<scale>-<width>x<height>-<appearance>.png` | 9,275 of 9,275 |
| Preview, versioned | `Previews/<same base>/<ZGENERATION>/Preview.png` | 180 directories |
| Preview, locked note | `Previews/<same base>.png.encrypted` | 17 files |
| Marked-up PDF fallback | `FallbackPDFs/<attachment id>/<ZFALLBACKPDFGENERATION>/FallbackPDF.pdf` | 19 of 19 |
| Marked-up PDF bundle | `Paper/Bundles/<attachment id>.bundle/` | 19 of 19 |

`ZFILESIZE` on media rows is usually NULL, so take file sizes from the disk instead.

Preview width and height are stored as floats and must be truncated to integers to build the name; truncation matched every row, rounding only 75%. Tables (331), URL cards (36), marked-up PDFs (19) and the drawing have no media row: their content lives in the database or in the paper bundle.

### Q7. Marked-up PDFs

A marked-up PDF is stored twice: as the original PDF plus the markup in a PaperKit bundle, and as a fallback PDF rendered with the markup. The fallback can be read on its own: all 19 are ordinary PDFs, and all 19 differ from their originals. In 16 the page count matches the original; in 3 it differs, which may be a rough count. `ZPAPERBUNDLEGENERATION` is empty for all 19, so bundles have no generation directory.

```
Paper/Bundles/<attachment id>.bundle/
  Assets.bundle/<base64 of SHA-256>      the original PDF; the name is its own content hash
  Database/data.sqlite3                  Coherence CRDT store (WAL file empty)
    Reference(Id, Version, RetainCount, ChildRetainCounts, Data)
      1 root row per bundle: 1-byte Id, protobuf Data
      449 object rows: 17-byte Id, 33-byte Version; 444 Data blobs = "crdt" + uint32 6 + protobuf
    Assets(Id, RetainCount, Data)
      1 row per bundle: Id = SHA-256 of the PDF in Assets.bundle (19 of 19), Data empty
```

The database belongs to Apple's private Coherence framework, the CRDT engine PaperKit links against. Its source files include `CRDataStoreBundle.swift` and `CRAssetManager.swift`, and it creates both tables with `CREATE TABLE IF NOT EXISTS`. Reference rows are reference-counted CRDT objects (the PaperKit page and markup model); bundles hold 3 to 138 of them. Asset file names are the hash in base64, with characters that are unsafe in file names substituted in 6 cases. Decoding the markup strokes inside the `crdt` blobs was not attempted.

### Q8. Attachment rows without a type

The gap is 26 rows, not \~38 as first estimated: 3,938 attachments minus 3,912 with a UTI. All 26 are unfetched iCloud placeholders:

- `ZTYPEUTI`, `ZMEDIA`, title, URL and mergeable data are all empty.
- All have `ZNEEDSINITIALFETCHFROMCLOUD = 1` and `ZNEEDSINITIALRELATIONSHIPSETUP = 1`.
- All belong to a note (6 notes in total), none are marked for deletion, and none have files on disk.

Whether those 6 notes show a broken attachment in the app is unchecked.

## Enums

### Q9. Paper style (ZPAPERSTYLETYPE)

Notes' code defines lined and grid paper as values 2 to 7, but this library only uses 0 (2,223 notes) and 1 (64 notes). Calling `+[ICPaperStyle linedPaperWithPaperStyleType:]` for each value returned the line spacing below; values 0, 1 and 8 or more return no paper.

| Value | Lines & Grids choice | Line spacing x, y (pt) | Confirmed by |
| --- | --- | --- | --- |
| 0 | Never set (likely Mac-created, imported or older iOS notes) |  | Code; meaning inferred |
| 1 | None |  | iPhone test |
| 2 | Grid, small | 27.9, 27.9 | Code and iPhone test |
| 3 | Grid, medium | 55.8, 55.8 | Code and iPhone test |
| 4 | Grid, large | 111.6, 111.6 | Code and iPhone test |
| 5 | Lines, small | 0, 27.9 | Code and iPhone test |
| 6 | Lines, medium | 0, 41.9 | Code and iPhone test |
| 7 | Lines, large | 0, 55.8 | Code and iPhone test |

The decompiled `+[ICPaperStyle linedPaperWithPaperStyleType:]` draws grids for 2 to 4, horizontal lines for 5 to 7, and nothing for any other value. On 2026-10-10, eight test notes made on an iPhone (default set to None) confirmed every name: a note left untouched and a note switched back to None both stored 1. So iPhone and iPad Notes write 1 for None when they create a note, while 0 means the value was never written. Value 1 first appears on notes created in 2018 and stays rare (64 notes); why most later notes still hold 0 is unconfirmed.

### Q10. Folder type (ZFOLDERTYPE)

Type 1 is Recently Deleted: the single type-1 folder carries that system title, and the decompiled `-[ICFolder isTrashFolder]` returns true when `folderType == 1` (or, for legacy folders, when the identifier starts with `TrashFolder`). `isSmartFolder` requires `folderType == 2` and a folder that is neither default nor trash. Trash is folder membership, not a flag: its 4 notes have `ZMARKEDFORDELETION = 0`, and no note in the library has that flag set.

| Value | Meaning | Folders | Notes in them |
| --- | --- | --- | --- |
| 0 | Regular folder (includes the default "Notes") | 133 | 1,897 |
| 1 | Recently Deleted | 1 | 4 |
| 2 | Smart folder | 7 | 0 (computed by query) |

386 notes have no folder at all. They overlap almost exactly with the 387 notes that have no body and no dates (see Note bodies).

### Q11. Attachment types 0 and 1

Both are real but special, confirmed from the decompiled code. Type 0 means the row has no UTI: in this library, exactly the 26 iCloud placeholders (Q8). Type 1 means unsupported: the row's `minimumSupportedNotesVersion` is newer than this Notes, or the note is locked and the UTI is not allowed in locked notes. No row in this library is type 1 today. Unknown file types (office, email, markdown, zip, `dyn.*`) fall to type 2.

## Structure: folders, dates and links

### Q12. Subfolders and smart folders

Subfolders are a plain parent pointer: `ZPARENT` on a folder row (Z\_ENT 15) holds the parent folder's `Z_PK`. 98 of 141 folders have a parent; the tree goes 4 levels deep.

| Depth | Folders |
| --- | --- |
| 0 (top level) | 43 |
| 1 | 51 |
| 2 | 30 |
| 3 | 13 |
| 4 | 4 |

Smart folders and Recently Deleted are always top level. Sidebar order is not stored in any obvious column: `ZSORTORDER` only takes 1, 2 or 3 (a section code, not a position), `ZNESTEDTITLEFORSORTING` is empty and `ZCUSTOMNOTESORTTYPEVALUE` is 0 everywhere. Order is probably alphabetical at runtime; not confirmed.

A smart folder is a saved query in `ZSMARTFOLDERQUERYJSON`. The 7 in this library use three shapes (tag names removed):

```
{"entity":"note","type":{"and":[{"tag":"<tag>"},{"deleted":false}]}}
{"entity":"note","type":{"and":[{"deleted":false},{"and":[{"pinned":true}]}]}}
{"entity":"note","type":{"and":[{"deleted":false},{"and":[{"modificationDateRelativeRange":{"type":6,"customAmount":1,"customUnit":2}}]}]}}
```

Filters are predicate objects (`tag`, `deleted`, `pinned`, `modificationDateRelativeRange`) inside `and` arrays, which can nest. Other filters Notes offers (checklists, attachments, shared, folders) will have their own keys not present here.

### Q13. Which dates are real

All dates are Core Data epoch values: seconds since 2001-01-01 UTC. Because entities share one table, each one uses a differently suffixed column.

| Entity | Created | Modified | Notes |
| --- | --- | --- | --- |
| Note (12) | `ZCREATIONDATE3` | `ZMODIFICATIONDATE1` | Set on 1,900 of 2,287 notes; years 2008 to 2026 |
| Attachment (5) | `ZCREATIONDATE` | `ZMODIFICATIONDATE` | 266 rows hold the sentinel -63114076800 (year 1) |
| Inline attachment (9) | `ZCREATIONDATE2` |  |  |
| Hashtag (8) | `ZCREATIONDATE1` |  |  |
| Folder (15) | none | `ZDATEFORLASTTITLEMODIFICATION`, `ZPARENTMODIFICATIONDATE` | Folders have no creation date |

Other note dates: `ZFOLDERMODIFICATIONDATE` (moved to folder), `ZLASTOPENEDDATE` (107 notes). `ZLASTVIEWEDMODIFICATIONDATE` is mostly negative and is a marker, not a real date.

### Q14. How a note link finds its target

A note link is an inline attachment with UTI `com.apple.notes.inlinetextattachment.link`. Its `ZTOKENCONTENTIDENTIFIER` holds a URL:

```
applenotes:note/<note UUID>?ownerIdentifier=_<32 hex>
```

All 29 links resolve: the UUID matches a note's `ZIDENTIFIER` (29 of 29). `ownerIdentifier` is the same on every row, likely the CloudKit user record name. The inline attachment UTIs are `com.apple.notes.inlinetextattachment.hashtag`, `.link`, `.dividerline` and `.mention`; they live in `ZTYPEUTI1` and join to the note through `ZNOTE1`. Hashtag inline attachments work the same way: their token text matches `ICHashtag.ZSTANDARDIZEDCONTENT` for 22 of 22.

## Method, privacy and limits

Every finding comes from the macOS build installed on 2026-09-24 and one iCloud account's library. Sources, in order of authority:

- **Shipped schema:** `NoteData.mom` decoded with the REA keyed-archive inspector (evidence `ev_3062bff9…a8a8`).
- **Notes' own code:** NotesShared and NotesUI loaded in a test program; side-effect-free class methods called against an in-memory store (UTI to type, paper style spacing).
- **The library:** a read-only snapshot of `NoteStore.sqlite`, plus directory listings and `file` type checks of the media folders.
- **Public format:** [apple\_cloud\_notes\_parser's notestore.proto](https://github.com/threeplanetssoftware/apple_cloud_notes_parser/blob/master/proto/notestore.proto) and its style constants.

No note text, titles, cell contents, file names, URLs or tag names are reproduced here; protobuf strings were reduced to their lengths before inspection.

**Decompiled code:** NotesShared and NotesUI were extracted from the dyld shared cache with Xcode's `dsc_extractor` and opened in REA (Hopper). Calls into other libraries were named by reading the selector stubs from a live process. Key evidence: `attachmentType` `ev_838ee449…`, `attachmentTypeFromTypeUTI` `ev_756157d0…`, `isTrashFolder` `ev_427485d9…`, `isSmartFolder` `ev_9edd6c99…`, `linedPaperWithPaperStyleType:` `ev_8359fca2…`, `topotext::String` serializer `ev_3769addf…`.

Still open:

- [x] Paper style value 1 = None, confirmed with iPhone test notes (resolved)
- [x] 326 missing tables: Evernote import left dangling placeholders; they show blank (resolved)
- [x] 13 extra U+FFFC characters: literal characters left by pasted rich text (resolved)
- [x] Table cell linkage traced on all 324 tables (resolved)
- [x] ParagraphStyle fields 3, 6, 7, 9 named by serialize round trip (resolved)
- [x] iCloud placeholders: stubs of notes gone from iCloud; opening one gets it cleaned up (resolved)
- [x] Marked-up PDF bundle: Coherence CRDT store plus hashed original PDF (resolved)
- [x] Attachment types 0, 1 and 7: decompiled
- [x] Folder type 1 = trash, 2 = smart: decompiled
- [x] Note fields 3 and 6: decompiled

## Reader recipe (distilled)

Read-only, against a copy of `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` and its `Accounts/<account-id>/` tree.

1. **Notes:** `Z_ENT = 12`. Skip stubs (`ZNEEDSINITIALFETCHFROMCLOUD = 1`, no folder). Locked notes (`ZISPASSWORDPROTECTED = 1`) are unreadable without the password.
2. **Folder:** note's folder via its folder FK; tree via `ZPARENT` on `Z_ENT = 15`. Type 1 = Recently Deleted, 2 = smart (query in `ZSMARTFOLDERQUERYJSON`, no members).
3. **Dates:** note created `ZCREATIONDATE3`, modified `ZMODIFICATIONDATE1`; add 978307200 for Unix time.
4. **Body:** `ZICNOTEDATA.ZDATA`, gunzip (or zlib for old rows), parse with `notestore.proto`. Walk `attribute_run` lengths in UTF-16 units over `note_text`. Map `style_type` (0 title, 1 heading, 2 subheading, 4 mono, 100 bullet, 101 dash, 102 numbered, 103 checklist).
5. **Attachments:** at each U+FFFC, take `attachment_info.attachment_identifier` -> `ZIDENTIFIER` (`ZNOTE` for attachments, `ZNOTE1` for inline). A U+FFFC with no `attachment_info` is a literal character: skip it. An identifier with no row (Evernote-imported tables) renders as a missing-table marker.
6. **By type:**
   - Media-backed (image, audio, movie, PDF, generic): `ZMEDIA` -> `Media/<media.ZIDENTIFIER>/<ZGENERATION1>/<ZFILENAME>`. Empty `ZFILENAME` = missing.
   - Table: gunzip `ZMERGEABLEDATA1`, `MergableDataProto`; resolve row/column slots through `ordering.contents`; missing cell = blank; ignore dead slot mappings.
   - URL card: `ZURLSTRING` (type 7 Map is a maps URL).
   - Marked-up PDF: `FallbackPDFs/<attachment id>/<ZFALLBACKPDFGENERATION>/FallbackPDF.pdf`.
   - Drawing: fallback image (path not traced; see consistency notes).
   - Type 0 (no UTI): unfetched placeholder, emit a marker.
7. **Inline:** note links `applenotes:note/<UUID>` in `ZTOKENCONTENTIDENTIFIER` -> note `ZIDENTIFIER`; hashtags match `ZSTANDARDIZEDCONTENT`.

## Consistency notes (open, minor)

- **Paper style corrects the first pass:** the 64 notes with `ZPAPERSTYLETYPE != 0` are value 1 = None, so no note in this library actually uses lined or grid paper.
- **Table counts:** Q5 says 322 tables decode and 9 have no data (331), but the trace covers "324 of 324". Re-count which is right.
- **Q2 matches vs rows:** 3,940 runs match a row, but only 3,912 attachment rows have a UTI. The extra 28 are likely attachments referenced more than once, or inline attachments; not stated.
- **Q2 misses:** 327 misses = 326 tables + 1 unexplained.
- **Trash flag:** Q10 says no note has `ZMARKEDFORDELETION = 1`, but the Q4 live test set it on one stub. Q10 likely predates the test snapshot.
- **Drawing (1) fallback image path** and **audio transcript fields** were not traced.
- **Sidebar folder order** is unconfirmed (probably alphabetical at runtime).
- **Markup strokes** inside PaperKit/Coherence `crdt` blobs are undecoded (fallback PDF makes this unnecessary for export).
