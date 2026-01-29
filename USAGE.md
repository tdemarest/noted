# Noted CLI Usage Guide

A comprehensive guide to using the `noted` CLI tool for working with Apple Notes.

## Table of Contents

- [Getting Started](#getting-started)
- [Listing Notes](#listing-notes)
- [Searching Notes](#searching-notes)
  - [Basic Search](#basic-search)
  - [Deep Search (FTS5)](#deep-search-fts5)
  - [FTS5 Query Syntax](#fts5-query-syntax)
- [Viewing Notes](#viewing-notes)
- [Exporting Notes](#exporting-notes)
  - [Single Note Export](#single-note-export)
  - [Bulk Export](#bulk-export)
- [Managing the Cache](#managing-the-cache)
- [Managing the Search Index](#managing-the-search-index)
- [Locked Notes](#locked-notes)

---

## Getting Started

Install dependencies and run commands with `uv`:

```bash
# Install dependencies
uv sync

# Verify installation
uv run noted --help
```

The CLI automatically caches a copy of the Apple Notes database to `~/.cache/noted/` and refreshes it when the source database changes.

---

## Listing Notes

List notes sorted by modification date (newest first):

```bash
# List all notes
uv run noted list

# Limit results
uv run noted list --limit 10
uv run noted list -n 20

# Filter by folder
uv run noted list --folder "Work"
uv run noted list -f "Projects"
```

### Counting Notes

```bash
# Total count
uv run noted count

# Count by folder
uv run noted count --by-folder
```

---

## Searching Notes

### Basic Search

Search titles and folder names (case-insensitive):

```bash
uv run noted list --search "meeting"
uv run noted list -s "project" --limit 20
```

### Deep Search (FTS5)

Search inside note content using SQLite FTS5 full-text search:

```bash
# Add --deep to search content
uv run noted list --search "budget" --deep
uv run noted list -s "quarterly review" -D

# Combine with folder filter
uv run noted list -s "meeting notes" -D --folder "Work"
```

### FTS5 Query Syntax

When using `--deep`, the search query supports FTS5 syntax:

| Syntax | Example | Description |
|--------|---------|-------------|
| Simple term | `budget` | Matches notes containing "budget" |
| Multiple terms | `budget meeting` | Implicit AND - both terms required |
| Phrase | `"project deadline"` | Exact phrase match (double quotes) |
| AND | `budget AND Q2` | Both terms required (uppercase) |
| OR | `budget OR expenses` | Either term matches (uppercase) |
| NOT | `budget NOT personal` | Exclude notes containing second term |
| Grouping | `(budget OR cost) AND Q2` | Parentheses control precedence |
| Prefix | `budg*` | Matches budget, budgeting, budgets... |
| Column filter | `title:meeting` | Search only in title |
| | `folder:Work` | Search only in folder name |
| | `content:deadline` | Search only in note content |

**Important:** Boolean operators must be **UPPERCASE**: `AND`, `OR`, `NOT`

#### Examples

```bash
# Exact phrase
uv run noted list -s '"quarterly review"' --deep

# Boolean OR
uv run noted list -s 'budget OR expenses' --deep

# Complex boolean with grouping
uv run noted list -s 'David AND (Andy OR Keith)' --deep
uv run noted list -s '(budget OR cost) AND Q2 NOT personal' --deep

# Prefix matching
uv run noted list -s 'secur*' --deep    # security, secure, secured...

# Column-specific search
uv run noted list -s 'title:meeting' --deep
uv run noted list -s 'folder:Work AND content:deadline' --deep
```

---

## Viewing Notes

View a note's full content by ID or UUID:

```bash
# Rich terminal output (default)
uv run noted view 42
uv run noted view "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"

# Output formats
uv run noted view 42 --markdown
uv run noted view 42 --json
uv run noted view 42 --json-styled    # Include formatting metadata
uv run noted view 42 --html

# Export to file
uv run noted view 42 --markdown -o ./my_note.md
uv run noted view 42 --html -o ./note.html
```

### Debug Mode

Show detailed note metadata (row ID, UUID, attachment stats):

```bash
uv run noted --debug view 42
uv run noted -d view 42
```

---

## Exporting Notes

### Single Note Export

Export a note with its attachments:

```bash
# Export to current directory
uv run noted export 42
# Creates: ./Note Title.md and ./Note Title_attachments/

# Export as 7zip archive
uv run noted export 42 --zip
# Creates: ./Note Title.7z

# Custom output location
uv run noted export 42 -o ~/Documents/mynote
```

### Bulk Export

Export all notes with folder structure preserved:

```bash
# Export all notes
uv run noted export --all
# Creates: ./notes_export/ with nested folders mirroring Apple Notes
# Example: notes_export/Work/Projects/Q1 Planning.md

# With 7zip archive
uv run noted export --all --zip
# Creates: ./notes_export/ AND ./notes_export.7z

# Custom output directory
uv run noted export --all -o ~/Backups/notes_2024-01-15

# Filter by folder
uv run noted export --all --folder "Work"

# Exclude deleted notes
uv run noted export --all --exclude-deleted

# Verbose output (show each note)
uv run noted export --all --verbose
```

### Export Output Structure

```
notes_export/
├── index.json              # Master manifest with all note metadata
├── Work/
│   ├── Projects/
│   │   ├── Q1 Planning.md
│   │   └── Q1 Planning_attachments/
│   │       ├── manifest.json
│   │       ├── screenshot.png
│   │       └── document.pdf
│   └── Meeting Notes.md
├── Personal/
│   └── Travel Ideas.md
└── Recently Deleted/
    └── Old Note.md
```

---

## Managing the Cache

The CLI caches the Apple Notes database for read-only access:

```bash
# Force refresh (clears cache and FTS index)
uv run noted refresh
```

Cache location: `~/.cache/noted/`

The cache auto-refreshes when the source database is newer.

---

## Managing the Search Index

The FTS5 search index is stored separately and auto-rebuilds when needed:

```bash
# Check index status
uv run noted index

# Force rebuild
uv run noted index --rebuild
```

Index location: `~/.cache/noted/fts_index.sqlite`

The index automatically rebuilds when:
- It doesn't exist
- The cached database has been updated since the index was built

---

## Locked Notes

Apple Notes that are password-protected (locked) cannot be read by this tool.

### Behavior

- **Viewing:** Shows error "Note is locked and cannot be read"
- **Exporting:** Creates placeholder file explaining the note is locked
- **Search Index:** Locked notes are skipped during indexing

### Export Handling

When exporting, locked notes are handled gracefully:

- Placeholder markdown file created with lock message
- `index.json` marks them with `"locked": true`
- Summary shows count: "3 locked notes (placeholders created)"

### Solution

To export locked notes: unlock them in Apple Notes first, then run the export again.
