# Noted CLI Usage Guide

A comprehensive guide to using the `noted` CLI tool for working with Apple Notes.

## Table of Contents

- [Getting Started](#getting-started)
  - [Shell Completion](#shell-completion-recommended)
- [Listing Notes](#listing-notes)
- [Tree View](#tree-view)
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

### Shell Completion (Recommended)

Set up tab-completion for a better command-line experience. This also creates a `noted` shell function so you can skip typing `uv run`.

**Zsh** (default on macOS) - Add to your `~/.zshrc`:

```zsh
# noted completion
_noted_completion() {
  eval $(env _TYPER_COMPLETE_ARGS="${words[1,$CURRENT]}" _NOTED_COMPLETE=complete_zsh uv run noted)
}

noted() {
    uv run noted "$@"
}

compdef _noted_completion noted
```

**Bash** - Add to your `~/.bashrc`:

```bash
# noted completion
_noted_completion() {
    COMPREPLY=( $(env _TYPER_COMPLETE_ARGS="${COMP_WORDS[*]}" _NOTED_COMPLETE=complete_bash uv run noted) )
}

noted() {
    uv run noted "$@"
}

complete -F _noted_completion noted
```

After adding, reload your shell:

```bash
source ~/.zshrc   # or ~/.bashrc for Bash
```

> **Why a function instead of an alias?** Aliases expand before completion runs, breaking the completion registration. Shell functions preserve the command name that completion hooks expect.

Now you can use `noted` directly with tab completion:

```bash
noted list --<TAB>        # Shows: --folder, --limit, --search, --deep, --tree, --verbose
noted view --<TAB>        # Shows: --markdown, --json, --html, --pdf, --export
noted export --<TAB>      # Shows: --all, --zip, --folder, --markdown, --json, --html
```

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

### Database Statistics

Get comprehensive statistics about your notes database:

```bash
# Show all statistics
uv run noted stats

# Include folder breakdown
uv run noted stats --by-folder

# JSON output for scripting
uv run noted stats --json

# Delete FTS index only (can be rebuilt from cache)
uv run noted stats --delete index
uv run noted stats -d index

# Delete cache DB and FTS index (forces fresh copy on next command)
uv run noted stats --delete cache
uv run noted stats -d cache
```

Example output:

```
Database Statistics
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cache
  Database size:       101.8 MB
  Last updated:        2025-01-30 00:29:24
  FTS index:           9.2 MB (1,877 notes) ✓
  Index built:         2025-01-30 00:55:38

Notes
  Total:                1,879
  Pinned:                  26
  Locked:                   3
  With checklists:        305 (251 incomplete)
  Recently deleted:         1

Attachments (4,035 total)
  PDFs:                 1,440
  Images:               1,928  (JPEG: 714, PNG: 559, HEIC: 284, GIF: 189, ...)
  Tables:                 494
  Links:                   36
  Office:                  42
  Emails:                  20
  Videos:                   8
  Drawings:                 1
  Other:                   66

  With location data:      91
```

---

## Tree View

Display notes and folders in a hierarchical tree structure:

```bash
# Show folder hierarchy with note counts
uv run noted list --tree
uv run noted list -t

# Include individual notes with icons
uv run noted list --tree --verbose
uv run noted list -t -v

# Filter to specific folder subtree
uv run noted list --tree -f "Work"

# Combine with search
uv run noted list --tree --verbose -s "meeting"
```

### Tree View Icons

| Icon | Meaning |
|------|---------|
| 📁 | Folder |
| 🗑️ | Recently Deleted folder |
| 📄 | Note |
| 🔒 | Locked (password-protected) |
| ✅ | Checklist complete |
| 🔲 | Checklist incomplete |
| 📷 | Image attachment |
| 📄 | PDF attachment |
| 📊 | Office document |
| 🎬 | Video |
| 🔗 | Link |
| 📎 | Other attachment |

### Example Output

Default tree (folders only):

```text
📁 Notes (1879)
├── 📁 Work (245)
│   ├── 📁 Projects (52)
│   │   └── 📁 2024 (18)
│   └── 📁 Meetings (89)
├── 📁 Personal (312)
└── 🗑️ Recently Deleted (4)
```

With `--verbose` (includes notes):

```text
📁 Notes (1879)
├── 📁 Work (245)
│   ├── 📄 Weekly Status 🔲 📷×2
│   ├── 📄 Budget Q1 ✅ 📊
│   ├── 📄 Passwords 🔒
│   └── 📁 Projects (52)
│       └── 📄 Roadmap 📄
└── 📁 Personal (312)
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

# Output formats (to terminal)
uv run noted view 42 --markdown
uv run noted view 42 --json
uv run noted view 42 --json-styled    # Include formatting metadata
uv run noted view 42 --html

# Export to file (filename auto-generated from note title)
uv run noted view 42 --export              # Creates "Note Title.txt"
uv run noted view 42 --export --markdown   # Creates "Note Title.md"
uv run noted view 42 --export --html       # Creates "Note Title.html"
uv run noted view 42 --export --json       # Creates "Note Title.json"
uv run noted view 42 --export --pdf        # Creates "Note Title.pdf"
```

The `--export` flag writes to the current directory with filename based on the note title. The extension is automatically selected based on the format option.

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
# Export to current directory (default: markdown)
uv run noted export 42
# Creates: ./Note Title.md and ./Note Title_attachments/

# Export in different formats
uv run noted export 42 --markdown      # Markdown (default)
uv run noted export 42 --json          # JSON
uv run noted export 42 --json-styled   # JSON with styling metadata
uv run noted export 42 --html          # Standalone HTML5

# Export as 7zip archive
uv run noted export 42 --zip
# Creates: ./Note Title.7z

# Custom output location
uv run noted export 42 -o ~/Documents/mynote
uv run noted export 42 --json -o ~/Documents/mynote.json
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
