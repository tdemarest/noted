# Apple Notes Timestamp Structure

> Canonical overview: [apple-notes-storage-reference.md](./apple-notes-storage-reference.md) (see Q13, "Which dates are real"). This deep-dive adds the column inventory, conversion code and common mistakes.

## Epoch

Core Data stores `REAL` seconds since 2001-01-01 00:00:00 UTC. Add `978307200` for Unix time.

```python
from datetime import UTC, datetime, timedelta

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def apple_timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert a Core Data timestamp to a datetime."""
    if timestamp is None:
        return None
    return APPLE_EPOCH + timedelta(seconds=timestamp)
```

| Apple timestamp | Unix timestamp | UTC |
|-----------------|----------------|-----|
| 0.0 | 978307200 | 2001-01-01 00:00:00 |
| 758629800.0 | 1736937000 | 2025-01-15 10:30:00 |

Because all entities share `ZICCLOUDSYNCINGOBJECT`, each entity uses a differently suffixed column for the same purpose (the suffix comes from Core Data attribute collisions between subentities).

## Columns for notes (Z_ENT = 12)

| Purpose | Column |
|---------|--------|
| Created | `ZCREATIONDATE3` |
| Modified | `ZMODIFICATIONDATE1` |
| Moved to folder | `ZFOLDERMODIFICATIONDATE` |
| Last opened | `ZLASTOPENEDDATE` |

`ZLASTVIEWEDMODIFICATIONDATE` is mostly negative and is a marker, not a date. iCloud stub rows (`ZNEEDSINITIALFETCHFROMCLOUD = 1`) have no dates at all.

The unsuffixed `ZCREATIONDATE` and `ZMODIFICATIONDATE` belong to attachments, not notes, so they are NULL on note rows. Attachments may hold the sentinel -63114076800 (year 1) for "never set".

## Columns by entity

| Entity | Created | Modified |
|--------|---------|----------|
| Note (12) | `ZCREATIONDATE3` | `ZMODIFICATIONDATE1` |
| Attachment (5) | `ZCREATIONDATE` | `ZMODIFICATIONDATE` |
| Inline attachment (9) | `ZCREATIONDATE2` | - |
| Hashtag (8) | `ZCREATIONDATE1` | - |
| Folder (15) | none | `ZDATEFORLASTTITLEMODIFICATION`, `ZPARENTMODIFICATIONDATE` |

Other timestamp-like columns seen in the table: `ZMODIFIEDDATE`, `ZSTATEMODIFICATIONDATE`, `ZPREVIEWUPDATEDATE`, `ZMODIFICATIONDATEATIMPORT`, `ZLEGACYMODIFICATIONDATEATIMPORT`, `ZLASTSYNCDATE`.

## Example SQL

```sql
SELECT
    n.Z_PK                AS id,
    n.ZIDENTIFIER         AS identifier,
    n.ZTITLE1             AS title,
    f.ZTITLE2             AS folder,
    n.ZCREATIONDATE3      AS created,
    n.ZMODIFICATIONDATE1  AS modified
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.Z_ENT = 12
  AND n.ZTITLE1 IS NOT NULL
ORDER BY n.ZMODIFICATIONDATE1 DESC;
```

`ZTITLE1 IS NOT NULL` is a valid note filter because iCloud stub rows have no title. To exclude the trash, filter on folder membership (see [the database-fields doc](./apple-notes-database-fields.md)), not on `ZMARKEDFORDELETION`.

Human-readable dates in SQL:

```sql
SELECT datetime(n.ZMODIFICATIONDATE1 + 978307200, 'unixepoch')
FROM ZICCLOUDSYNCINGOBJECT n
WHERE n.Z_ENT = 12;
```

## Common mistakes

```sql
-- Wrong: NULL for notes
SELECT ZCREATIONDATE, ZMODIFICATIONDATE FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 12;
-- Right
SELECT ZCREATIONDATE3, ZMODIFICATIONDATE1 FROM ZICCLOUDSYNCINGOBJECT WHERE Z_ENT = 12;
```

- Forgetting the conversion: use `apple_timestamp_to_datetime` from `noted.db`.
- Ordering by `ZMODIFICATIONDATE` instead of `ZMODIFICATIONDATE1`.

## Working on a copy

Copy `NoteStore.sqlite`, `-shm` and `-wal` before querying and open the copy read-only:

```python
conn = sqlite3.connect(f"file:{cache_dir}/NoteStore.sqlite?mode=ro", uri=True)
```
