# Apple Notes Timestamp Structure

This document describes the timestamp columns in the Apple Notes SQLite database and how to correctly query creation and modification dates for notes.

## Overview

Apple Notes uses **Core Data** as its persistence framework, which stores timestamps as **seconds since January 1, 2001 00:00:00 UTC** (the "Apple epoch"). The database schema is polymorphic, meaning different entity types share the same table (`ZICCLOUDSYNCINGOBJECT`) with different columns populated depending on the entity type.

Key characteristics:
- Timestamps are stored as `REAL` (floating-point) values
- The Apple epoch offset from Unix epoch is **978307200 seconds**
- Different entity types use different timestamp column suffixes
- Notes use `ZCREATIONDATE3` and `ZMODIFICATIONDATE1`

## Core Data Timestamp Conversion

### Apple Epoch

```
Apple Epoch:  2001-01-01 00:00:00 UTC
Unix Epoch:   1970-01-01 00:00:00 UTC
Offset:       978307200 seconds (31 years)
```

### Conversion Formula

```python
from datetime import UTC, datetime, timedelta

# Apple epoch as datetime
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)

def apple_timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert Apple Core Data timestamp to datetime."""
    if timestamp is None:
        return None
    return APPLE_EPOCH + timedelta(seconds=timestamp)

# Alternative using Unix epoch offset
def apple_to_unix(apple_ts: float) -> float:
    return apple_ts + 978307200
```

### Example Conversions

| Apple Timestamp | Unix Timestamp | DateTime (UTC) |
|-----------------|----------------|----------------|
| 0.0 | 978307200 | 2001-01-01 00:00:00 |
| 758629800.0 | 1736937000 | 2025-01-15 10:30:00 |
| 791357276.244246 | 1769664476.244246 | 2026-01-29 05:27:56 |

## Timestamp Columns in ZICCLOUDSYNCINGOBJECT

The `ZICCLOUDSYNCINGOBJECT` table contains many timestamp-related columns due to its polymorphic nature. Different columns are populated depending on the entity type (note, folder, attachment, etc.).

### Available Timestamp Columns

| Column Name | Data Type | Description |
|-------------|-----------|-------------|
| `ZCREATIONDATE` | REAL | Creation date (unused for notes) |
| `ZCREATIONDATE1` | REAL | Creation date variant 1 (unused for notes) |
| `ZCREATIONDATE2` | REAL | Creation date variant 2 (unused for notes) |
| `ZCREATIONDATE3` | REAL | **Creation date for notes** |
| `ZMODIFICATIONDATE` | REAL | Modification date (unused for notes) |
| `ZMODIFICATIONDATE1` | REAL | **Modification date for notes** |
| `ZMODIFIEDDATE` | REAL | Modified date (different entity types) |
| `ZSTATEMODIFICATIONDATE` | REAL | State modification tracking |
| `ZFOLDERMODIFICATIONDATE` | REAL | Folder modification tracking |
| `ZPREVIEWUPDATEDATE` | REAL | Preview generation date |
| `ZLASTOPENEDDATE` | REAL | Last opened date |
| `ZLASTVIEWEDMODIFICATIONDATE` | REAL | Last viewed modification |
| `ZDATEFORLASTTITLEMODIFICATION` | REAL | Title modification date |
| `ZPARENTMODIFICATIONDATE` | REAL | Parent object modification |
| `ZMODIFICATIONDATEATIMPORT` | REAL | Import timestamp |
| `ZLEGACYMODIFICATIONDATEATIMPORT` | REAL | Legacy import timestamp |

### Columns Used for Notes

For note entities (records with `ZTITLE1 IS NOT NULL`):

| Purpose | Column Name | Coverage |
|---------|-------------|----------|
| **Created** | `ZCREATIONDATE3` | 100% of notes |
| **Modified** | `ZMODIFICATIONDATE1` | 100% of notes |

**Important**: The base columns `ZCREATIONDATE` and `ZMODIFICATIONDATE` (without numeric suffixes) are **always NULL** for note entities.

### Column Coverage Analysis

Based on analysis of a database with 1,880 notes:

```
ZCREATIONDATE:        0 notes (0%)
ZCREATIONDATE1:       0 notes (0%)
ZCREATIONDATE2:       0 notes (0%)
ZCREATIONDATE3:    1880 notes (100%)  ← Use this
ZMODIFICATIONDATE:    0 notes (0%)
ZMODIFICATIONDATE1: 1880 notes (100%)  ← Use this
```

## Correct SQL Queries

### List Notes with Timestamps

```sql
SELECT
    n.Z_PK as id,
    n.ZIDENTIFIER as identifier,
    n.ZTITLE1 as title,
    f.ZTITLE2 as folder,
    n.ZCREATIONDATE3 as created,      -- NOT ZCREATIONDATE
    n.ZMODIFICATIONDATE1 as modified  -- NOT ZMODIFICATIONDATE
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.ZTITLE1 IS NOT NULL
  AND n.ZMARKEDFORDELETION != 1
ORDER BY n.ZMODIFICATIONDATE1 DESC;
```

### Get Single Note by ID

```sql
SELECT
    n.Z_PK as id,
    n.ZIDENTIFIER as identifier,
    n.ZTITLE1 as title,
    f.ZTITLE2 as folder,
    n.ZCREATIONDATE3 as created,
    n.ZMODIFICATIONDATE1 as modified
FROM ZICCLOUDSYNCINGOBJECT n
LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
WHERE n.Z_PK = ?
  AND n.ZTITLE1 IS NOT NULL;
```

## Common Mistakes

### Wrong Column Names

```sql
-- WRONG: These columns are always NULL for notes
SELECT ZCREATIONDATE, ZMODIFICATIONDATE FROM ZICCLOUDSYNCINGOBJECT;

-- CORRECT: Use the numbered suffix columns
SELECT ZCREATIONDATE3, ZMODIFICATIONDATE1 FROM ZICCLOUDSYNCINGOBJECT;
```

### Forgetting Timestamp Conversion

```python
# WRONG: Raw Apple timestamp
created = row["ZCREATIONDATE3"]  # Returns 791357276.244246

# CORRECT: Convert to datetime
from noted.db import apple_timestamp_to_datetime
created = apple_timestamp_to_datetime(row["ZCREATIONDATE3"])
# Returns datetime(2026, 1, 29, 5, 27, 56, 244246, tzinfo=UTC)
```

### Incorrect ORDER BY

```sql
-- WRONG: Column is always NULL
ORDER BY n.ZMODIFICATIONDATE DESC

-- CORRECT: Use the numbered suffix
ORDER BY n.ZMODIFICATIONDATE1 DESC
```

## Why Multiple Timestamp Columns?

Apple Notes uses Core Data with a **polymorphic table design** where multiple entity types share `ZICCLOUDSYNCINGOBJECT`:

| Entity Type | Identifier Column | Timestamp Columns |
|-------------|-------------------|-------------------|
| Notes | `ZTITLE1` | `ZCREATIONDATE3`, `ZMODIFICATIONDATE1` |
| Folders | `ZTITLE2` | Various |
| Attachments | `ZTYPEUTI` | Various |
| Media | `ZFILENAME` | Various |

Each entity type may use different columns for the same logical purpose. The numbered suffixes (1, 2, 3) typically correspond to different Core Data entity definitions in the data model.

## Database Location

```
~/Library/Group Containers/group.com.apple.notes/
├── NoteStore.sqlite       # Main database
├── NoteStore.sqlite-shm   # Shared memory file
└── NoteStore.sqlite-wal   # Write-ahead log
```

**Important**: Always copy these files before querying. Never operate directly on the live database.

```python
import shutil
from pathlib import Path

NOTES_DIR = Path.home() / "Library/Group Containers/group.com.apple.notes"
CACHE_DIR = Path.home() / ".cache/noted"

# Copy all SQLite files
for filename in ["NoteStore.sqlite", "NoteStore.sqlite-shm", "NoteStore.sqlite-wal"]:
    src = NOTES_DIR / filename
    if src.exists():
        shutil.copy2(src, CACHE_DIR / filename)

# Open in read-only mode
conn = sqlite3.connect(f"file:{CACHE_DIR}/NoteStore.sqlite?mode=ro", uri=True)
```

## Sample Output

With correct column names:

```
                                     Notes
┏━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ ID     ┃ Title          ┃ Folder          ┃ Created        ┃ Modified        ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ 16110  │ David Kuei 1:1 │ Adeia One on    │ 2022-03-22     │ 2026-01-29      │
│        │                │ Ones            │ 21:17          │ 22:07           │
│ 22461  │ My Sample Note │ Imported Notes  │ 2026-01-29     │ 2026-01-29      │
│        │                │ 1               │ 06:52          │ 07:49           │
│ 40     │ EDC            │ Imported Notes  │ 2014-06-24     │ 2026-01-29      │
│        │                │                 │ 02:51          │ 05:27           │
└────────┴────────────────┴─────────────────┴────────────────┴─────────────────┘
```

## References

- Apple Notes database: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- Core Data timestamp epoch: 2001-01-01 00:00:00 UTC
- Note entities: `ZICCLOUDSYNCINGOBJECT` where `ZTITLE1 IS NOT NULL`
- Creation timestamp: `ZCREATIONDATE3` column
- Modification timestamp: `ZMODIFICATIONDATE1` column
