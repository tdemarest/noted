# Apple Notes Database Fields Reference

> Canonical overview: [apple-notes-storage-reference.md](./apple-notes-storage-reference.md) (entity table, attachment types, enums, folders, dates). This deep-dive lists the column-level detail the reference leaves out: note flags, attachment intelligence fields, locations, smart folder queries, hashtags, sharing, encryption and sync columns, with example SQL.

Related deep-dives: [attachments](./apple-notes-attachment-structure.md), [tables](./apple-notes-crdt-table-structure.md), [formatting](./apple-notes-formatting-structure.md), [timestamps](./apple-notes-timestamp-structure.md).

## Entity filters

Core Data stores most entities in `ZICCLOUDSYNCINGOBJECT`, distinguished by `Z_ENT` (full table in the reference).

```sql
SELECT * FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 12;  -- notes
SELECT * FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 15;  -- folders
SELECT * FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 5;   -- attachments
```

Entities not listed in the reference: 3 `ICCloudSyncingObject` (abstract base), 4 `ICAccountData`, 7 `ICDeviceMigrationState`, 10 `ICLegacyTombstone`, 13 `ICNoteContainer` (abstract), 17 `ICLocation` (abstract), 22 `ICServerChangeToken`.

`ZTITLE1 IS NOT NULL` works as a note filter (folders use `ZTITLE2`, attachments `ZTYPEUTI`) because iCloud stub rows (`ZNEEDSINITIALFETCHFROMCLOUD = 1`) have no title. `Z_ENT = 12` is the precise filter.

## Note flags

| Column | Description |
|--------|-------------|
| `ZISPINNED` | Pinned (1) |
| `ZISPASSWORDPROTECTED` | Locked (1); body is an `ICCryptoEncryptionObject` plist |
| `ZMARKEDFORDELETION` | Normally 0, even for trashed notes (see below) |
| `ZNOTEHASCHANGES` | Has pending changes |
| `ZLEGACYNOTEWASPLAINTEXT` | Imported from plain text |
| `ZHASCHECKLIST` | Contains checklist items |
| `ZHASCHECKLISTINPROGRESS` | Has unchecked items |
| `ZHASEMPHASIS` | Has bold or italic text |
| `ZHASSYSTEMTEXTATTACHMENTS` | Has inline system attachments |
| `ZISSYSTEMPAPER` | Uses a system paper template |
| `ZPREFERREDBACKGROUNDTYPE` | NULL or 0 |
| `ZPAPERSTYLETYPE` | 0 never set, 1 none, 2-4 grid small/medium/large, 5-7 lines small/medium/large |

Snippets and titles: `ZSNIPPET` (first-line excerpt), `ZWIDGETSNIPPET` (longer excerpt for widgets), `ZFALLBACKTITLE`, `ZFALLBACKSUBTITLEIOS`, `ZFALLBACKSUBTITLEMAC`.

### Recently Deleted

Trash is folder membership, not a flag. A note is in Recently Deleted when its folder has `ZFOLDERTYPE = 1`. `ZMARKEDFORDELETION` is normally 0 for trashed notes (Notes sets it only in rare cases, such as when it cleans up an unavailable stub), so check both, as `deleted_note_sql` in `src/noted/db.py` does.

```sql
-- Notes in Recently Deleted
SELECT n.Z_PK AS id, n.ZTITLE1 AS title
FROM ZICCLOUDSYNCINGOBJECT n
JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.Z_ENT = 12
  AND f.ZFOLDERTYPE = 1;

-- Live notes (exclude trash)
SELECT n.Z_PK AS id, n.ZTITLE1 AS title
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.Z_ENT = 12
  AND n.ZTITLE1 IS NOT NULL
  AND IFNULL(n.ZMARKEDFORDELETION, 0) = 0
  AND IFNULL(f.ZFOLDERTYPE, 0) != 1;
```

### Example: note metadata

```sql
SELECT
    n.Z_PK AS id,
    n.ZTITLE1 AS title,
    n.ZISPINNED AS pinned,
    n.ZISPASSWORDPROTECTED AS locked,
    n.ZHASCHECKLIST AS has_checklist,
    n.ZHASCHECKLISTINPROGRESS AS checklist_incomplete,
    n.ZSNIPPET AS snippet
FROM ZICCLOUDSYNCINGOBJECT n
WHERE n.Z_ENT = 12 AND n.ZTITLE1 IS NOT NULL
ORDER BY n.ZISPINNED DESC, n.ZMODIFICATIONDATE1 DESC;
```

### Example: checklists in progress

```sql
SELECT n.Z_PK AS id, n.ZTITLE1 AS title, f.ZTITLE2 AS folder
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.Z_ENT = 12
  AND n.ZHASCHECKLISTINPROGRESS = 1
ORDER BY n.ZMODIFICATIONDATE1 DESC;
```

## Attachment intelligence fields

Notes analyses image attachments and stores results for search.

| Column | Description |
|--------|-------------|
| `ZOCRSUMMARY` | Recognised text; each line may be followed by tab-indented alternatives |
| `ZOCRSUMMARYVERSION` | OCR algorithm version |
| `ZIMAGECLASSIFICATIONSUMMARY` | Space-separated content tags (for example `Document Chart Outdoor`) |
| `ZIMAGECLASSIFICATIONSUMMARYVERSION` | Classifier version |
| `ZHANDWRITINGSUMMARY` | Recognised handwriting (Apple Pencil) |
| `ZHANDWRITINGSUMMARYVERSION` | Handwriting version |

OCR summary shape (invented example):

```
Example Line One
	Example Line Onc      <- alternative
Example Line Two
	Example Line Tvvo     <- alternative
```

```sql
SELECT a.ZTITLE AS filename, a.ZTYPEUTI AS type, n.ZTITLE1 AS note_title
FROM ZICCLOUDSYNCINGOBJECT a
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE a.ZOCRSUMMARY LIKE '%search_term%';
```

## Attachment metadata

| Column | Description |
|--------|-------------|
| `ZSIZEWIDTH`, `ZSIZEHEIGHT` | Pixel size |
| `ZWIDTH`, `ZHEIGHT` | Alternative size fields |
| `ZDURATION` | Media duration in seconds |
| `ZSCALE` | Display scale |
| `ZORIENTATION` | EXIF-style orientation (1-8) |
| `ZTITLE` | System title |
| `ZUSERTITLE` | User-renamed title |
| `ZALTTEXT` | Alt text; the `#tag` text for hashtags |
| `ZDISPLAYTEXT` | Display text for inline items |
| `ZATTACHMENTVIEWTYPE` | 0 inline, 1 thumbnail |
| `ZURLSTRING` | URL for URL cards (type 7 Map is a maps URL) |
| `ZURLEXPIRED` | Link no longer valid |
| `ZREMOTEFILEURLSTRING` | Remote file URL |

```sql
SELECT a.ZTITLE, a.ZTYPEUTI, a.ZSIZEWIDTH, a.ZSIZEHEIGHT, a.ZDURATION, n.ZTITLE1
FROM ZICCLOUDSYNCINGOBJECT a
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE a.ZSIZEWIDTH > 1000 OR a.ZDURATION > 0
ORDER BY a.ZSIZEWIDTH * a.ZSIZEHEIGHT DESC;
```

Attachment counts per note:

```sql
SELECT n.Z_PK, n.ZTITLE1, COUNT(a.Z_PK) AS attachment_count,
       GROUP_CONCAT(DISTINCT a.ZTYPEUTI) AS types
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT a ON a.ZNOTE = n.Z_PK AND a.ZTYPEUTI IS NOT NULL
WHERE n.Z_ENT = 12 AND n.ZTITLE1 IS NOT NULL
GROUP BY n.Z_PK
HAVING attachment_count > 0
ORDER BY attachment_count DESC
LIMIT 20;
```

## Inline attachments (Z_ENT = 9)

Hashtags, note links, dividers and mentions are inline attachments. They join to the note through `ZNOTE1` and keep their UTI in `ZTYPEUTI1` (regular attachments use `ZTYPEUTI`).

| Column | Description |
|--------|-------------|
| `ZNOTE1` | Parent note `Z_PK` |
| `ZTYPEUTI1` | `com.apple.notes.inlinetextattachment.hashtag`, `.link`, `.dividerline`, `.mention` |
| `ZALTTEXT` | Visible text, for example `#example` |
| `ZTOKENCONTENTIDENTIFIER` | Hashtag: normalised tag name. Link: `applenotes:note/<UUID>?ownerIdentifier=...`, where the UUID is the target note's `ZIDENTIFIER` |
| `ZIDENTIFIER` | UUID matched by the body's `attachment_identifier` |

```sql
-- Hashtags with note titles
SELECT tag.ZALTTEXT AS hashtag, tag.ZTOKENCONTENTIDENTIFIER AS tag_name,
       n.ZTITLE1 AS note_title, n.Z_PK AS note_id
FROM ZICCLOUDSYNCINGOBJECT tag
JOIN ZICCLOUDSYNCINGOBJECT n ON tag.ZNOTE1 = n.Z_PK
WHERE tag.ZTYPEUTI1 = 'com.apple.notes.inlinetextattachment.hashtag'
ORDER BY tag.ZTOKENCONTENTIDENTIFIER, n.ZTITLE1;

-- Tags with note counts
SELECT tag.ZTOKENCONTENTIDENTIFIER AS tag_name, COUNT(DISTINCT tag.ZNOTE1) AS note_count
FROM ZICCLOUDSYNCINGOBJECT tag
WHERE tag.ZTYPEUTI1 = 'com.apple.notes.inlinetextattachment.hashtag'
GROUP BY tag.ZTOKENCONTENTIDENTIFIER
ORDER BY note_count DESC;
```

Hashtag tokens match `ICHashtag.ZSTANDARDIZEDCONTENT` (Z_ENT = 8). Add the trash filter from "Recently Deleted" above when counting only live notes.

## Locations (ZICLOCATION)

Photos with GPS data have a row in `ZICLOCATION`.

```sql
CREATE TABLE ZICLOCATION (
    Z_PK INTEGER PRIMARY KEY,
    Z_ENT INTEGER,              -- 17 ICLocation, 18 ICAttachmentLocation
    Z_OPT INTEGER,
    ZPLACEUPDATED INTEGER,      -- place has been geocoded
    ZATTACHMENT INTEGER,        -- FK to the attachment row
    ZLATITUDE FLOAT,
    ZLONGITUDE FLOAT,
    ZPLACEMARKDATA BLOB         -- serialized CLPlacemark (bplist)
);
```

`ZPLACEMARKDATA` holds address, city/state/country, postal code and points of interest.

```sql
SELECT l.ZLATITUDE, l.ZLONGITUDE, a.ZTITLE, n.ZTITLE1
FROM ZICLOCATION l
JOIN ZICCLOUDSYNCINGOBJECT a ON l.ZATTACHMENT = a.Z_PK
JOIN ZICCLOUDSYNCINGOBJECT n ON a.ZNOTE = n.Z_PK
WHERE l.ZLATITUDE IS NOT NULL;
```

## Folders (Z_ENT = 15)

| Column | Description |
|--------|-------------|
| `ZTITLE2` | Folder name |
| `ZFOLDERTYPE` | 0 regular, 1 Recently Deleted, 2 smart folder |
| `ZPARENT` | Parent folder `Z_PK` |
| `ZSMARTFOLDERQUERYJSON` | Smart folder query |
| `ZSORTORDER` | Section code (1, 2 or 3), not a position |
| `ZNESTEDTITLEFORSORTING` | Observed empty |
| `ZIMPORTEDFROMLEGACY` | Imported from old Notes |

Sidebar order is not stored in an obvious column (see the reference).

```sql
SELECT f.Z_PK AS id, f.ZTITLE2 AS name, f.ZFOLDERTYPE AS type, p.ZTITLE2 AS parent_name
FROM ZICCLOUDSYNCINGOBJECT f
LEFT JOIN ZICCLOUDSYNCINGOBJECT p ON f.ZPARENT = p.Z_PK
WHERE f.Z_ENT = 15
ORDER BY p.ZTITLE2, f.ZTITLE2;
```

### Smart folder query format

Smart folders (`ZFOLDERTYPE = 2`) have no members in `ZFOLDER`; notes are matched by evaluating `ZSMARTFOLDERQUERYJSON`. Filters are predicate objects inside nestable `and` arrays.

```json
{"entity": "note", "type": {"and": [{"tag": "EXAMPLE"}, {"deleted": false}]}}
```

```json
{"entity": "note", "type": {"and": [{"deleted": false}, {"and": [{"pinned": true}]}]}}
```

```json
{"entity": "note", "type": {"and": [{"deleted": false}, {"and": [
  {"modificationDateRelativeRange": {"type": 6, "customAmount": 1, "customUnit": 2}}
]}]}}
```

| Condition | Meaning | Database equivalent |
|-----------|---------|---------------------|
| `{"tag": "NAME"}` | Notes with that hashtag | Inline hashtag attachment with `ZTOKENCONTENTIDENTIFIER = 'NAME'` |
| `{"pinned": true}` | Pinned | `ZISPINNED = 1` |
| `{"pinned": false}` | Not pinned | `ZISPINNED = 0 OR ZISPINNED IS NULL` |
| `{"deleted": false}` | Not in the trash | Not in a `ZFOLDERTYPE = 1` folder |
| `{"deleted": true}` | In the trash | In a `ZFOLDERTYPE = 1` folder |
| `{"modificationDateRelativeRange": {...}}` | Recently modified | `ZMODIFICATIONDATE1 >= threshold` |

`customUnit` for `modificationDateRelativeRange`: 0 minutes, 1 hours, 2 days, 3 weeks, 4 months, 5 years. Other filters Notes offers (checklists, attachments, shared, folders) have their own keys not seen in observed data.

```sql
-- Count notes for a tag-based smart folder (live notes only)
SELECT COUNT(DISTINCT n.Z_PK)
FROM ZICCLOUDSYNCINGOBJECT n
JOIN ZICCLOUDSYNCINGOBJECT tag ON tag.ZNOTE1 = n.Z_PK
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE tag.ZTYPEUTI1 = 'com.apple.notes.inlinetextattachment.hashtag'
  AND tag.ZTOKENCONTENTIDENTIFIER = 'EXAMPLE'
  AND n.Z_ENT = 12 AND n.ZTITLE1 IS NOT NULL
  AND IFNULL(n.ZMARKEDFORDELETION, 0) = 0
  AND IFNULL(f.ZFOLDERTYPE, 0) != 1;
```

## Accounts (Z_ENT = 14)

| Column | Description |
|--------|-------------|
| `ZNAME` | Account name |
| `ZACCOUNTTYPE` | 1 = iCloud |
| `ZUSERRECORDNAME` | CloudKit user record id |
| `ZDIDCHOOSETOMIGRATE`, `ZDIDFINISHMIGRATION`, `ZDIDMIGRATEONMAC` | Migration state |

## Sharing

`ZICINVITATION` (shared notes and folders) key columns: `ZNOTECOUNT`, `ZNOTECOUNTRECURSIVE`, `ZSUBFOLDERCOUNT`, `ZSUBFOLDERCOUNTRECURSIVE`, `ZACCOUNT`, `ZROOTOBJECT` (shared note or folder), `ZROOTOBJECTTYPE`, `ZCREATIONDATE`, `ZMODIFICATIONDATE`, `ZRECEIVEDDATE`, `ZSNIPPET`, `ZTITLE`, `ZSHAREURL`, `ZSERVERSHAREDATA`, `ZTHUMBNAILDATADARK`, `ZTHUMBNAILDATALIGHT`.

`ZICNOTEPARTICIPANT`: `ZNOTE` (note FK), `ZPARTICIPANTID`, `ZUSERID`.

## Encryption (locked notes)

| Column | Description |
|--------|-------------|
| `ZISPASSWORDPROTECTED` | Note is locked |
| `ZCRYPTOITERATIONCOUNT` | PBKDF2 iterations |
| `ZCRYPTOINITIALIZATIONVECTOR` | AES IV |
| `ZCRYPTOSALT` | Salt |
| `ZCRYPTOTAG` | Authentication tag |
| `ZCRYPTOWRAPPEDKEY` | Wrapped key |
| `ZCRYPTOVERIFIER` | Password verifier |
| `ZPASSWORDHINT` | Hint |

The body in `ZICNOTEDATA.ZDATA` is an NSKeyedArchiver plist (root class `ICCryptoEncryptionObject`) and cannot be read without the password.

## Cloud sync

| Column | Description |
|--------|-------------|
| `ZCLOUDSTATE` | Sync state |
| `ZNEEDSINITIALFETCHFROMCLOUD` | 1 for iCloud stub rows (no title, folder, dates or body) |
| `ZNEEDSTOBEFETCHEDFROMCLOUD` | Needs sync from cloud |
| `ZNEEDSTOSAVEUSERSPECIFICRECORD` | User record needs save |
| `ZLASTSYNCDATE` | Last successful sync |
| `ZSERVERRECORDDATA` | CloudKit record data |
| `ZSERVERSHAREDATA` | CloudKit share data |

## ZICNOTEDATA

```sql
CREATE TABLE ZICNOTEDATA (
    Z_PK INTEGER PRIMARY KEY,
    ZNOTE INTEGER,                      -- FK to the note
    ZCRYPTOINITIALIZATIONVECTOR BLOB,   -- locked notes only
    ZCRYPTOTAG BLOB,                    -- locked notes only
    ZDATA BLOB                          -- gzip (occasionally zlib) protobuf, or a keyed-archive plist when locked
);
```
