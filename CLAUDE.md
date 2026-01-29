# Project: Apple Notes Utility

## PROJECT CONTEXT

A Python CLI tool for working directly the Apple Note sqlite database. The project aims
to be able to:

- Make a copy of the Apple Note sqlite database and '-wal' an '-shm' files before opening and manipulating the database during development.
  - Write operations will be accessible in production.
- Read, write, create, delete notes.
- List notes
- Count notes
- Search notes
- Export notes to markdown, JSON, HTML or PDF formats

## Apple Database Structure

Key tables include:

- ZICCLOUDSYNCINGOBJECT: Main table containing notes, folders, attachments
- ZICNOTEDATA: The actual note content (compressed)

### Note Content Format

The note body is stored in a compressed, protobuf format:

- Located in ZICNOTEDATA.ZDATA
- Gzip-compressed protobuf data
- Contains rich text formatting, embedded images, checklists, etc.

Protobuf libraries to consider:

pyrobuf:

- An alternative that generates Cython code for significantly improved performance (2-4x faster than the official C++-backed library, and 20-40x faster than pure-Python).
- Best for: Performance-critical applications where maximum serialization/deserialization speed is essential.

betterproto:

- This library aims to provide a more idiomatic Python experience by leveraging modern language features like dataclasses, type checking (mypy), and async/await for gRPC.
- Best for: Developers prioritizing clean, readable, and modern Python code with strong static type checking.

## QUICK START

```bash
# Install dependencies
uv sync

# List notes (most recently modified first)
uv run noted list

# List notes with filters
uv run noted list --folder "Work" --limit 10

# Count all notes
uv run noted count

# Count notes by folder
uv run noted count --by-folder

# View a note (rich terminal output)
uv run noted view <note_id>

# View note as markdown
uv run noted view <note_id> --markdown

# View note as JSON
uv run noted view <note_id> --json

# View note as HTML
uv run noted view <note_id> --html

# Export note to file (format auto-detected from flags)
uv run noted view <note_id> --markdown -o ./my_note.md

# Export note with attachments
uv run noted view <note_id> --attachments
# Creates: ./Note_Title.md and ./Note_Title_attachments/

# Export note with attachments to specific path
uv run noted view <note_id> -a -o ./backup/my_note

# Export note and attachments as 7zip archive
uv run noted view <note_id> --attachments --zip
# Creates: ./Note_Title.7z

# Force refresh cached database
uv run noted refresh
```

The CLI automatically caches a copy of the Apple Notes database to `~/.cache/noted/` and refreshes it when the source database changes.

## ENVIRONMENT VARIABLES

Claude to complete this later as env variables are added

### Using 1Password CLI

The `.env` file contains `op://` secret references for use with 1Password CLI:

```bash
# Run any command with secrets injected
op run --env-file .env -- uv run ...

# Test that secrets are loading
op run --env-file .env -- printenv | grep -E "ANTHROPIC|OPENAI|SLACK|BRAVE"
```

Edit `.env` to customize the `op://VAULT/ITEM/FIELD` paths to match your 1Password vault structure.

## PACKAGE STRUCTURE

```shell
noted/
├── pyproject.toml          # Project config, dependencies, CLI entry point
├── uv.lock                  # Locked dependencies
├── src/noted/
│   ├── __init__.py         # Package version
│   ├── attachments.py      # Attachment export, archive creation
│   ├── cli.py              # Typer CLI commands (list, count, view, refresh)
│   ├── db.py               # Database caching, connection, queries
│   ├── display.py          # Rich terminal output formatting
│   ├── models.py           # Note, NoteSummary, Attachment dataclasses
│   ├── protobuf.py         # Protobuf parsing for note content
│   └── tables.py           # Apple Notes CRDT table parsing
├── tests/
│   ├── test_attachments.py # Attachment export tests
│   ├── test_cli.py         # CLI command tests
│   ├── test_db.py          # Database function tests
│   ├── test_display.py     # Display function tests
│   ├── test_integration.py # Integration tests
│   ├── test_models.py      # Model tests
│   ├── test_protobuf.py    # Protobuf parsing tests
│   └── test_tables.py      # Table parsing tests
└── docs/
    ├── apple-notes-attachment-structure.md  # Attachment storage documentation
    ├── apple-notes-crdt-table-structure.md  # Table CRDT documentation
    └── plans/              # Design and implementation plans
```

## CRITICAL RULES

- The Apple Notes data location is located: ~/Library/Group Containers/group.com.apple.notes
  - The SQLite database is: NoteStore.sqlite
  - The SHM file is: NoteStore.sqlite-shm
  - The WAL file is: NoteStore.sqlite-wal
- Make copies of the sqlite files and never operate on the live versions
  - Do somnthing like:

```python
shutil.copy('NoteStore.sqlite', '/tmp/notes_copy.sqlite')
```

- Use read only mode in development:
  
```python
# URI mode with read-only flag
conn = sqlite3.connect('file:path/to/db.sqlite?mode=ro', uri=True)
```

- Never truncate data in report output - all text must be visible

Note: Apple uses Core Data timestamps (seconds since Jan 1, 2001), so you add 978307200 to convert to Unix epoch.

## TECH STACK

- Python 3.14+
- uv - Package management (NOT pip)
- Ruff - Formatting and linting
- Pyrefly - Type checking
- Pytest - Testing
- Typer - CLI framework, command line options
- rich - Terminal output
- loguru - Logging (Colorized=True)

## CODE CONVENTIONS

- Keep source code file to ~1000 lines or less. This does not apply to output files like HTML/CSS.
  - Write modular, resuable and clean code.
- PEP-8 naming for all identifiers
- Type hints required everywhere, including tests
- Docstrings required for all modules, functions, classes, methods
- No star imports (`from foo import *`)
- Prefer async calls for services
- ISO 8601 dates (YYYY-MM-DD)
- UUID7 for unique IDs (Python 3.14+)
- pathlib.Path for all file paths (not os.path)
- Prefer clean, simple code over clever complexity
- Use XDG-style directories and file locations as required

## INPUT/OUTPUT

- Default input location: `input/` (searched recursively)
- Default output location: `output/` (created if missing)
- Command line options can override defaults

## TESTING

- Framework: pytest with `tests/` directory
- Run: `uv run pytest`

## FUTURE ROADMAP

TBD

## WORKFLOW INSTRUCTIONS

- Always read relevant files before making changes
- Update or create documentation in `docs/`
- Use sub-agents for specialized tasks
- Ensure type checking and linting pass before committing
- Create meaningful commit messages
- Use Claude Tasks for tracking work (not beads)
- No commits until there are zero Pyrefly and ruff warnings or errors
- Git commits use conventional commit format like docs:, feat():, fix()
