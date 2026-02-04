# Apple Notes Database Fields Reference

This document provides a comprehensive reference for fields in the Apple Notes SQLite database (`NoteStore.sqlite`). It covers undocumented fields discovered through database analysis that complement the existing documentation on attachments, tables, formatting, and timestamps.

## Overview

Apple Notes uses Core Data with a **polymorphic table design**. The main table `ZICCLOUDSYNCINGOBJECT` stores multiple entity types (notes, folders, attachments, media, accounts) with different columns populated depending on the entity type.

Key characteristics:
- Entity type is determined by `Z_ENT` column (see Entity Types section)
- Notes have `ZTITLE1 IS NOT NULL`
- Folders have `ZTITLE2 IS NOT NULL`
- Attachments have `ZTYPEUTI IS NOT NULL`
- Many columns use numbered suffixes (e.g., `ZCREATIONDATE3`) for different entity types

## Database Location

```
~/Library/Group Containers/group.com.apple.notes/
├── NoteStore.sqlite       # Main database
├── NoteStore.sqlite-shm   # Shared memory file
└── NoteStore.sqlite-wal   # Write-ahead log
```

**Important**: Always copy these files before querying. Never operate directly on the live database.

## Entity Types (Z_PRIMARYKEY)

The `Z_PRIMARYKEY` table defines all entity types in the database:

| Z_ENT | Entity Name | Description |
|-------|-------------|-------------|
| 1 | ICAssetSignature | Asset signatures for sync |
| 2 | ICCloudState | Cloud sync state |
| 3 | ICCloudSyncingObject | Base class (polymorphic) |
| 4 | ICAccountData | Account data storage |
| 5 | ICAttachment | File attachments |
| 6 | ICAttachmentPreviewImage | Attachment previews |
| 7 | ICDeviceMigrationState | Device migration tracking |
| 8 | ICHashtag | Hashtag references |
| 9 | ICInlineAttachment | Inline attachments |
| 10 | ICLegacyTombstone | Deleted item markers |
| 11 | ICMedia | Media file records |
| 12 | ICNote | Notes |
| 13 | ICNoteContainer | Container base class |
| 14 | ICAccount | User accounts |
| 15 | ICFolder | Folders |
| 16 | ICInvitation | Share invitations |
| 17 | ICLocation | Location base class |
| 18 | ICAttachmentLocation | Photo GPS locations |
| 19 | ICNoteData | Note content (ZDATA) |
| 20 | ICNoteParticipant | Shared note participants |
| 21 | ICServerChangeToken | Sync tokens |

### Querying by Entity Type

```sql
-- Get all notes
SELECT * FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 12;

-- Get all folders
SELECT * FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 15;

-- Get all attachments
SELECT * FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 5;
```

## Note-Level Metadata

These fields are populated for note entities (`ZTITLE1 IS NOT NULL`):

### Status Flags

| Column | Type | Description | Values |
|--------|------|-------------|--------|
| `ZISPINNED` | INTEGER | Note pinned to top of list | 0=no, 1=yes |
| `ZISPASSWORDPROTECTED` | INTEGER | Note is password-locked | 0=no, 1=yes |
| `ZMARKEDFORDELETION` | INTEGER | Note is in Recently Deleted | 0=no, 1=yes |
| `ZNOTEHASCHANGES` | INTEGER | Note has unsaved changes | 0=no, 1=yes |
| `ZLEGACYNOTEWASPLAINTEXT` | INTEGER | Imported from plain text | 0=no, 1=yes |

### Content Indicators

| Column | Type | Description | Values |
|--------|------|-------------|--------|
| `ZHASCHECKLIST` | INTEGER | Note contains checklist items | 0=no, 1=yes |
| `ZHASCHECKLISTINPROGRESS` | INTEGER | Checklist has incomplete items | 0=no, 1=yes |
| `ZHASEMPHASIS` | INTEGER | Note has text emphasis (bold/italic) | 0=no, 1=yes |
| `ZHASSYSTEMTEXTATTACHMENTS` | INTEGER | Has system text attachments | 0=no, 1=yes |

### Paper and Background

| Column | Type | Description | Values |
|--------|------|-------------|--------|
| `ZPAPERSTYLETYPE` | INTEGER | Paper style for handwriting | 0=blank, 1=lined/grid |
| `ZISSYSTEMPAPER` | INTEGER | Uses system paper template | 0=no, 1=yes |
| `ZPREFERREDBACKGROUNDTYPE` | INTEGER | Background preference | NULL or 0 |

### Snippets and Previews

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ZSNIPPET` | VARCHAR | Plain text excerpt (first line) | `"Meeting notes for..."` |
| `ZWIDGETSNIPPET` | VARCHAR | Longer excerpt for iOS/macOS widgets | Multi-line preview text |
| `ZFALLBACKTITLE` | VARCHAR | Fallback title if main unavailable | Title string |
| `ZFALLBACKSUBTITLEIOS` | VARCHAR | iOS fallback subtitle | Subtitle string |
| `ZFALLBACKSUBTITLEMAC` | VARCHAR | macOS fallback subtitle | Subtitle string |

### Example Query: Note Metadata

```sql
SELECT
    n.Z_PK as id,
    n.ZTITLE1 as title,
    n.ZISPINNED as pinned,
    n.ZISPASSWORDPROTECTED as locked,
    n.ZHASCHECKLIST as has_checklist,
    n.ZHASCHECKLISTINPROGRESS as checklist_incomplete,
    n.ZSNIPPET as snippet,
    n.ZWIDGETSNIPPET as widget_snippet
FROM ZICCLOUDSYNCINGOBJECT n
WHERE n.ZTITLE1 IS NOT NULL
  AND n.ZMARKEDFORDELETION != 1
ORDER BY n.ZISPINNED DESC, n.ZMODIFICATIONDATE1 DESC;
```

## Attachment Intelligence Fields

Apple Notes performs AI analysis on image attachments, storing results for search indexing.

### OCR (Optical Character Recognition)

| Column | Type | Description |
|--------|------|-------------|
| `ZOCRSUMMARY` | VARCHAR | Extracted text from images |
| `ZOCRSUMMARYVERSION` | INTEGER | OCR algorithm version |

The `ZOCRSUMMARY` field contains recognized text with multiple confidence alternatives separated by newlines and tabs:

```
408.533.8509          ← Primary recognition
	406.533.8509      ← Alternative 1
	408.535.8509      ← Alternative 2
Technical Solutions Engineer
	Technical Solution Engineer
	Technical Solutions Enqineer
```

### Image Classification

| Column | Type | Description |
|--------|------|-------------|
| `ZIMAGECLASSIFICATIONSUMMARY` | VARCHAR | Content tags for images |
| `ZIMAGECLASSIFICATIONSUMMARYVERSION` | INTEGER | Classification algorithm version |

Classification contains space-separated tags describing image content:

```
Document Documents Papers Written Document Handwriting Chart Charts Graph Graphs
```

Common classifications:
- `Document`, `Papers`, `Written Document`
- `Chart`, `Graph`, `Whiteboard`
- `Sign`, `Signs`
- `Outdoor`, `Sky`, `Night Sky`
- `Tableware`, `Utensil`, `Plate`

### Handwriting Recognition

| Column | Type | Description |
|--------|------|-------------|
| `ZHANDWRITINGSUMMARY` | VARCHAR | Recognized handwriting text |
| `ZHANDWRITINGSUMMARYVERSION` | INTEGER | Handwriting algorithm version |

Used for Apple Pencil drawings and handwritten notes.

### Example Query: Search Attachments by OCR

```sql
SELECT
    a.ZTITLE as filename,
    a.ZTYPEUTI as type,
    a.ZOCRSUMMARY as ocr_text,
    n.ZTITLE1 as note_title
FROM ZICCLOUDSYNCINGOBJECT a
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE a.ZOCRSUMMARY LIKE '%phone%'
   OR a.ZOCRSUMMARY LIKE '%address%';
```

## Attachment Metadata

### Dimensions and Duration

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ZSIZEWIDTH` | FLOAT | Width in pixels | `1920.0` |
| `ZSIZEHEIGHT` | FLOAT | Height in pixels | `1080.0` |
| `ZWIDTH` | FLOAT | Alternative width field | `1920.0` |
| `ZHEIGHT` | FLOAT | Alternative height field | `1080.0` |
| `ZDURATION` | FLOAT | Media duration in seconds | `30.5` |
| `ZSCALE` | FLOAT | Display scale factor | `1.0`, `2.0` |
| `ZORIENTATION` | INTEGER | Image orientation (EXIF) | 1-8 |

### Display and Titles

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ZTITLE` | VARCHAR | System-assigned title | `"IMG_1234.jpg"` |
| `ZUSERTITLE` | VARCHAR | User-renamed title | `"Vacation Photo.jpg"` |
| `ZALTTEXT` | VARCHAR | Accessibility alt text | Often hashtags: `#template` |
| `ZDISPLAYTEXT` | VARCHAR | Display text for inline items | `"waiting"`, `"tbd"` |
| `ZATTACHMENTVIEWTYPE` | INTEGER | Display mode | 0=inline, 1=thumbnail |

### URLs and Links

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ZURLSTRING` | VARCHAR | URL for link attachments | `"https://example.com"` |
| `ZURLEXPIRED` | INTEGER | Link is no longer valid | 0=valid, 1=expired |
| `ZREMOTEFILEURLSTRING` | VARCHAR | Remote file URL | Cloud storage URLs |

### Attachment Types Distribution

Common `ZTYPEUTI` values found in Apple Notes:

| UTI | Description | Typical Count |
|-----|-------------|---------------|
| `com.adobe.pdf` | PDF documents | High |
| `public.jpeg` | JPEG images | High |
| `public.png` | PNG images | High |
| `public.heic` | HEIC images (iPhone) | Medium |
| `com.apple.notes.table` | Embedded tables | Medium |
| `com.compuserve.gif` | GIF images | Medium |
| `org.webmproject.webp` | WebP images | Low |
| `public.url` | Web links | Low |
| `com.apple.mail.email` | Email attachments | Low |
| `com.apple.paper.doc.pdf` | Paper documents | Low |
| `org.openxmlformats.spreadsheetml.sheet` | Excel files | Low |
| `org.openxmlformats.wordprocessingml.document` | Word files | Low |
| `public.comma-separated-values-text` | CSV files | Low |
| `com.apple.quicktime-movie` | QuickTime video | Low |
| `public.mpeg-4` | MP4 video | Low |
| `public.python-script` | Python files | Rare |
| `com.apple.drawing.2` | Apple Pencil drawings | Rare |

### Example Query: Large Attachments

```sql
SELECT
    a.ZTITLE as filename,
    a.ZTYPEUTI as type,
    a.ZSIZEWIDTH as width,
    a.ZSIZEHEIGHT as height,
    a.ZDURATION as duration_seconds,
    n.ZTITLE1 as note_title
FROM ZICCLOUDSYNCINGOBJECT a
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE a.ZSIZEWIDTH > 1000
   OR a.ZDURATION > 0
ORDER BY a.ZSIZEWIDTH * a.ZSIZEHEIGHT DESC;
```

## Location Data (ZICLOCATION)

Photos with embedded GPS data have location records in the `ZICLOCATION` table.

### Schema

```sql
CREATE TABLE ZICLOCATION (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,              -- Entity type (17=ICLocation, 18=ICAttachmentLocation)
    Z_OPT INTEGER,
    ZPLACEUPDATED INTEGER,      -- Place info has been geocoded
    ZATTACHMENT INTEGER,        -- FK to attachment in ZICCLOUDSYNCINGOBJECT
    ZLATITUDE FLOAT,            -- GPS latitude
    ZLONGITUDE FLOAT,           -- GPS longitude
    ZPLACEMARKDATA BLOB         -- Serialized CLPlacemark (bplist)
);
```

### Example Query: Photos with Location

```sql
SELECT
    l.ZLATITUDE as lat,
    l.ZLONGITUDE as lng,
    a.ZTITLE as filename,
    a.ZTYPEUTI as type,
    n.ZTITLE1 as note_title
FROM ZICLOCATION l
JOIN ZICCLOUDSYNCINGOBJECT a ON l.ZATTACHMENT = a.Z_PK
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE l.ZLATITUDE IS NOT NULL;
```

### Placemark Data

The `ZPLACEMARKDATA` blob contains a serialized `CLPlacemark` in bplist format with:
- Street address
- City, state, country
- Postal code
- Points of interest

## Folder Metadata

### Fields

| Column | Type | Description | Values |
|--------|------|-------------|--------|
| `ZTITLE2` | VARCHAR | Folder name | `"Work"`, `"Personal"` |
| `ZFOLDERTYPE` | INTEGER | Folder type | 0=regular, 1=system (Recently Deleted), 2=smart folder |
| `ZPARENT` | INTEGER | Parent folder FK | For nested folders |
| `ZNESTEDTITLEFORSORTING` | VARCHAR | Full path for sorting | For hierarchy |
| `ZSMARTFOLDERQUERYJSON` | VARCHAR | Smart folder query | JSON query definition |
| `ZSORTORDER` | INTEGER | Manual sort position | Integer ordering |
| `ZIMPORTEDFROMLEGACY` | INTEGER | Imported from old Notes | 0=no, 1=yes |

### Example Query: Folder Hierarchy

```sql
SELECT
    f.Z_PK as id,
    f.ZTITLE2 as name,
    f.ZFOLDERTYPE as type,
    p.ZTITLE2 as parent_name
FROM ZICCLOUDSYNCINGOBJECT f
LEFT JOIN ZICCLOUDSYNCINGOBJECT p ON f.ZPARENT = p.Z_PK
WHERE f.ZTITLE2 IS NOT NULL
ORDER BY f.ZNESTEDTITLEFORSORTING;
```

### Smart Folder Query Format

Smart folders (ZFOLDERTYPE=2) use `ZSMARTFOLDERQUERYJSON` to define their filter criteria.
The JSON structure supports various query types:

**Tag-based smart folders:**
```json
{
  "entity": "note",
  "type": {
    "and": [
      {"tag": "TODO"},
      {"deleted": false}
    ]
  }
}
```

**Pinned notes smart folder:**
```json
{
  "entity": "note",
  "type": {
    "and": [
      {"deleted": false},
      {"and": [{"pinned": true}]}
    ]
  }
}
```

**Date-based smart folder (recent edits):**
```json
{
  "entity": "note",
  "type": {
    "and": [
      {"deleted": false},
      {"and": [
        {"modificationDateRelativeRange": {
          "type": 6,
          "customAmount": 1,
          "customUnit": 2
        }}
      ]}
    ]
  }
}
```

## Account Information

### Fields in ZICCLOUDSYNCINGOBJECT

| Column | Type | Description |
|--------|------|-------------|
| `ZNAME` | VARCHAR | Account name (e.g., "iCloud") |
| `ZACCOUNTTYPE` | INTEGER | Account type (1=iCloud) |
| `ZUSERRECORDNAME` | VARCHAR | CloudKit user record ID |
| `ZDIDCHOOSETOMIGRATE` | INTEGER | User chose to migrate |
| `ZDIDFINISHMIGRATION` | INTEGER | Migration completed |
| `ZDIDMIGRATEONMAC` | INTEGER | Migrated on macOS |

### Example Query: Account Info

```sql
SELECT
    Z_PK as id,
    ZNAME as name,
    ZACCOUNTTYPE as type,
    ZUSERRECORDNAME as user_id
FROM ZICCLOUDSYNCINGOBJECT
WHERE ZNAME IS NOT NULL;
```

## Sharing and Collaboration

### ZICINVITATION Table

Stores information about shared notes and folders:

```sql
CREATE TABLE ZICINVITATION (
    Z_PK INTEGER PRIMARY KEY,
    ZNOTECOUNT INTEGER,              -- Number of shared notes
    ZNOTECOUNTRECURSIVE INTEGER,     -- Including subfolders
    ZSNIPPETATTACHMENTCOUNT INTEGER,
    ZSNIPPETATTACHMENTTYPE INTEGER,
    ZSUBFOLDERCOUNT INTEGER,
    ZSUBFOLDERCOUNTRECURSIVE INTEGER,
    ZACCOUNT INTEGER,                -- FK to account
    ZROOTOBJECT INTEGER,             -- FK to shared note/folder
    ZCREATIONDATE TIMESTAMP,         -- When share was created
    ZMODIFICATIONDATE TIMESTAMP,
    ZRECEIVEDDATE TIMESTAMP,         -- When invitation received
    ZROOTOBJECTTYPE VARCHAR,         -- Type of shared object
    ZSNIPPET VARCHAR,                -- Preview text
    ZTITLE VARCHAR,                  -- Share title
    ZSHAREURL VARCHAR,               -- Unique share URL
    ZSERVERSHAREDATA BLOB,           -- Server sync data
    ZTHUMBNAILDATADARK BLOB,         -- Dark mode thumbnail
    ZTHUMBNAILDATALIGHT BLOB         -- Light mode thumbnail
);
```

### ZICNOTEPARTICIPANT Table

Tracks participants in shared notes:

```sql
CREATE TABLE ZICNOTEPARTICIPANT (
    Z_PK INTEGER PRIMARY KEY,
    ZNOTE INTEGER,           -- FK to note
    ZPARTICIPANTID VARCHAR,  -- Participant identifier
    ZUSERID VARCHAR          -- User identifier
);
```

## Encryption Fields

For password-protected notes:

| Column | Type | Description |
|--------|------|-------------|
| `ZISPASSWORDPROTECTED` | INTEGER | Note is encrypted |
| `ZCRYPTOITERATIONCOUNT` | INTEGER | PBKDF2 iteration count |
| `ZCRYPTOINITIALIZATIONVECTOR` | BLOB | AES IV |
| `ZCRYPTOSALT` | BLOB | Password salt |
| `ZCRYPTOTAG` | BLOB | Authentication tag |
| `ZCRYPTOWRAPPEDKEY` | BLOB | Wrapped encryption key |
| `ZCRYPTOVERIFIER` | BLOB | Password verifier |
| `ZPASSWORDHINT` | VARCHAR | User's password hint |

**Note**: Encrypted note content in `ZICNOTEDATA.ZDATA` cannot be decrypted without the user's password.

## Cloud Sync Fields

| Column | Type | Description |
|--------|------|-------------|
| `ZCLOUDSTATE` | INTEGER | Current sync state |
| `ZNEEDSINITIALFETCHFROMCLOUD` | INTEGER | Needs initial download |
| `ZNEEDSTOBEFETCHEDFROMCLOUD` | INTEGER | Needs sync from cloud |
| `ZNEEDSTOSAVEUSERSPECIFICRECORD` | INTEGER | User record needs save |
| `ZLASTSYNCDATE` | TIMESTAMP | Last successful sync |
| `ZSERVERRECORDDATA` | BLOB | CloudKit record data |
| `ZSERVERSHAREDATA` | BLOB | CloudKit share data |

## Additional Tables

### ZICNOTEDATA

Stores the actual note content:

```sql
CREATE TABLE ZICNOTEDATA (
    Z_PK INTEGER PRIMARY KEY,
    ZNOTE INTEGER,                      -- FK to note
    ZCRYPTOINITIALIZATIONVECTOR BLOB,   -- For encrypted notes
    ZCRYPTOTAG BLOB,                    -- For encrypted notes
    ZDATA BLOB                          -- Gzip-compressed protobuf
);
```

### ZICCLOUDSTATE

Tracks cloud sync state for objects:

```sql
-- Check sync status
SELECT COUNT(*) FROM ZICCLOUDSTATE;
```

### ZICSERVERCHANGETOKEN

Stores sync tokens for incremental updates:

```sql
-- View sync tokens
SELECT * FROM ZICSERVERCHANGETOKEN;
```

## Useful Queries

### Notes with Checklists In Progress

```sql
SELECT
    n.Z_PK as id,
    n.ZTITLE1 as title,
    f.ZTITLE2 as folder
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.ZTITLE1 IS NOT NULL
  AND n.ZHASCHECKLISTINPROGRESS = 1
  AND n.ZMARKEDFORDELETION != 1
ORDER BY n.ZMODIFICATIONDATE1 DESC;
```

### Pinned Notes

```sql
SELECT
    n.Z_PK as id,
    n.ZTITLE1 as title,
    f.ZTITLE2 as folder
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.ZTITLE1 IS NOT NULL
  AND n.ZISPINNED = 1
  AND n.ZMARKEDFORDELETION != 1;
```

### Recently Deleted Notes

```sql
SELECT
    n.Z_PK as id,
    n.ZTITLE1 as title,
    datetime(n.ZMODIFICATIONDATE1 + 978307200, 'unixepoch') as deleted_at
FROM ZICCLOUDSYNCINGOBJECT n
WHERE n.ZTITLE1 IS NOT NULL
  AND n.ZMARKEDFORDELETION = 1
ORDER BY n.ZMODIFICATIONDATE1 DESC;
```

### Attachment Statistics by Note

```sql
SELECT
    n.Z_PK as note_id,
    n.ZTITLE1 as title,
    COUNT(a.Z_PK) as attachment_count,
    GROUP_CONCAT(DISTINCT a.ZTYPEUTI) as types
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT a ON a.ZNOTE = n.Z_PK AND a.ZTYPEUTI IS NOT NULL
WHERE n.ZTITLE1 IS NOT NULL
  AND n.ZMARKEDFORDELETION != 1
GROUP BY n.Z_PK
HAVING attachment_count > 0
ORDER BY attachment_count DESC
LIMIT 20;
```

### Search OCR Text

```sql
SELECT
    a.ZTITLE as filename,
    a.ZOCRSUMMARY as ocr_text,
    n.ZTITLE1 as note_title
FROM ZICCLOUDSYNCINGOBJECT a
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE a.ZOCRSUMMARY LIKE '%search_term%'
  AND n.ZMARKEDFORDELETION != 1;
```

## References

- Database location: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- Main table: `ZICCLOUDSYNCINGOBJECT` (polymorphic)
- Note content: `ZICNOTEDATA.ZDATA` (gzip-compressed protobuf)
- Related docs:
  - [Apple Notes Attachment Structure](./apple-notes-attachment-structure.md)
  - [Apple Notes CRDT Table Structure](./apple-notes-crdt-table-structure.md)
  - [Apple Notes Formatting Structure](./apple-notes-formatting-structure.md)
  - [Apple Notes Timestamp Structure](./apple-notes-timestamp-structure.md)
