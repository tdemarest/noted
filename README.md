<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Python][python-shield]][python-url]
[![License][license-shield]][license-url]
[![Contributors][contributors-shield]][contributors-url]
[![Issues][issues-shield]][issues-url]

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h1>noted</h1>
  <p>
    A Python CLI tool for reading, exporting, and working with Apple Notes directly from the SQLite database.
    <br />
    <a href="#usage"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/tdemarest/noted/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/tdemarest/noted/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#features">Features</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#list-notes">List Notes</a></li>
        <li><a href="#count-notes">Count Notes</a></li>
        <li><a href="#view-a-note">View a Note</a></li>
        <li><a href="#export-formats">Export Formats</a></li>
        <li><a href="#export-notes">Export Notes</a></li>
        <li><a href="#full-export">Full Export</a></li>
        <li><a href="#locked-notes">Locked Notes</a></li>
      </ul>
    </li>
    <li><a href="#how-it-works">How It Works</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About The Project

Apple Notes is a powerful note-taking app, but accessing your notes programmatically has always been challenging. **noted** provides direct read access to your Apple Notes database, allowing you to:

- **Search and browse** your entire notes library from the command line
- **Export notes** in multiple formats (Markdown, JSON, HTML)
- **Extract attachments** including images, PDFs, and other files
- **Parse complex content** including tables stored in Apple's CRDT format

The tool works by safely copying and reading the Apple Notes SQLite database — it never modifies your original notes.

## CAVEAT EMPTOR

I am NOT a software developer. This was built 100% in an initial 30 minute, vibe-coded session because I needed
something that worked with a large-ish number of Notes. Other features were added over a couple hours. It does
exactly what I need it to and maybe it saves someone some hours or tokens if they need a similar utility.

### Features

- **Rich terminal output** with syntax highlighting and formatted tables
- **Multiple export formats**: Markdown, JSON, HTML
- **Attachment extraction** with manifest generation
- **7zip archive creation** good for notes that have lots of attachments
- **Table parsing** from Apple's proprietary CRDT format
- **UUID and row ID support** for note identification
- **Automatic database caching** with smart refresh detection
- **Debug mode** for detailed note metadata

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

- [![Claude Code][claude-badge]][claude-url] Claude Code - AI-powered development
- [![Python][python-badge]][python-url] Python 3.14+
- [![Typer][typer-badge]][typer-url] Typer - CLI framework
- [![Rich][rich-badge]][rich-url] Rich - Terminal formatting
- [betterproto](https://github.com/danielgtaylor/python-betterproto) - Protobuf parsing
- [py7zr](https://github.com/miurahr/py7zr) - 7zip archive creation
- [loguru](https://github.com/Delgan/loguru) - Logging

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

- **macOS** (Apple Notes database access required)
- **Python 3.14+**
- **[uv](https://github.com/astral-sh/uv)** - Fast Python package manager

This was dveloped and tested solely on macOS Tahoe 26.2 with Notes Version 4.13 (3146.61.8).

Install uv if you haven't already:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/tdemarest/noted.git
   cd noted
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Verify installation:
   ```bash
   uv run noted --help
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

The CLI automatically caches a copy of the Apple Notes database to `~/.cache/noted/` and refreshes it when the source database changes.

### List Notes

List all notes, sorted by most recently modified:

```bash
uv run noted list
```

Filter by folder and limit results:

```bash
uv run noted list --folder "Work" --limit 10
```

### Count Notes

Count all notes:

```bash
uv run noted count
```

Count notes grouped by folder:

```bash
uv run noted count --by-folder
```

### View a Note

View a note with rich terminal formatting. You can use either the row ID or UUID:

```bash
# By row ID
uv run noted view 42

# By UUID
uv run noted view "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
```

Enable debug mode for detailed metadata (UUID, row ID, attachment stats):

```bash
uv run noted --debug view 42
uv run noted -d view 42
```

### Export Formats

Export notes in different formats:

```bash
# Markdown
uv run noted view 42 --markdown
uv run noted view 42 --markdown -o ./my_note.md

# JSON
uv run noted view 42 --json

# HTML
uv run noted view 42 --html
```

### Export Notes

Export a single note with all its attachments using the `export` command:

```bash
# Export to current directory
uv run noted export 42
# Creates: ./Note Title.md and ./Note Title_attachments/

# Export to specific path
uv run noted export 42 -o ./backup/my_note

# Export as 7zip archive
uv run noted export 42 --zip
# Creates: ./Note Title.7z
```

### Full Export

Export ALL notes with nested folder structure mirroring Apple Notes:

```bash
# Export all notes
uv run noted export --all
# Creates: ./notes_export/ with full folder hierarchy
# Example: notes_export/Work/Projects/Meeting Notes.md

# Export with 7zip archive
uv run noted export --all --zip
# Creates: ./notes_export/ AND ./notes_export.7z
# Progress: "Exporting notes... 150/150 notes" then "Creating archive... 412/412 files"

# Export to custom directory
uv run noted export --all -o ~/Backups/notes_2026-01-29

# Export only notes from a specific folder (matches anywhere in path)
uv run noted export --all --folder "Work"

# Export excluding deleted notes
uv run noted export --all --exclude-deleted

# Verbose mode (show each note as exported)
uv run noted export --all --verbose
```

The full export creates an `index.json` manifest at the root with statistics and note metadata.

Each note's attachments directory includes a `manifest.json`:

```json
{
  "note_id": 42,
  "note_identifier": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
  "note_title": "My Note",
  "exported_at": "2026-01-29T10:30:00.000Z",
  "attachments": [
    {
      "identifier": "11111111-2222-3333-4444-555555555555",
      "filename": "photo.jpg",
      "type_uti": "public.jpeg",
      "exported": true
    }
  ]
}
```

### Locked Notes

Apple Notes that are password-protected cannot be read by this tool:

- Locked notes are detected and skipped (content is encrypted)
- A placeholder markdown file is created explaining the note is locked
- The `index.json` manifest marks these with `"locked": true`
- Summary shows: "3 locked notes (placeholders created)"

**To export locked notes:** Unlock them in Apple Notes first, then run the export again.

### Refresh Database Cache

Force a refresh of the cached database:

```bash
uv run noted refresh
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## How It Works

**noted** accesses your Apple Notes by:

1. **Copying the database** - The SQLite database at `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` is copied to a cache directory. The original is never modified.

2. **Parsing note content** - Note bodies are stored as gzip-compressed protobuf data. The tool decompresses and parses this format to extract text, formatting, and embedded content.

3. **Extracting attachments** - Attachments (images, PDFs, etc.) are stored as files on disk, with the database containing references. The tool resolves these references and copies files during export.

4. **Parsing tables** - Apple Notes tables use a CRDT (Conflict-free Replicated Data Type) format for sync. The tool reverse-engineers this format to reconstruct tables in display order.

### Database Structure

| Table | Purpose |
|-------|---------|
| `ZICCLOUDSYNCINGOBJECT` | Notes, folders, and attachments |
| `ZICNOTEDATA` | Compressed note content (protobuf) |

### Supported Attachment Types

| Type | UTI | Exportable |
|------|-----|------------|
| Images | `public.jpeg`, `public.png`, `public.heic` | Yes |
| PDFs | `com.adobe.pdf`, `public.pdf` | Yes |
| Drawings | `com.apple.drawing` | Yes |
| Tables | `com.apple.notes.table` | Rendered inline |
| Links | `public.url` | Rendered inline |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [x] List and count notes
- [x] View notes with rich formatting
- [x] Export to Markdown, JSON, HTML
- [x] Extract attachments
- [x] Parse embedded tables
- [x] 7zip archive export
- [x] UUID-based note lookup
- [x] Full export with nested folder hierarchy
- [x] Progress bars for export operations
- [x] Locked note detection and placeholders
- [ ] Search notes by content
- [ ] PDF export


See the [open issues](https://github.com/tdemarest/noted/issues) for a full list of proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions are welcome! If you have a suggestion that would make this better:

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests: `uv run pytest`
5. Run linting: `uv run ruff check .`
6. Commit your Changes (`git commit -m 'feat: add amazing feature'`)
7. Push to the Branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Setup

```bash
# Install with dev dependencies
uv sync

# Run tests
uv run pytest

# Run linting
uv run ruff check .

# Run type checking
uv run pyrefly check src/
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - AI pair programmer that wrote the vast majority of this codebase
- [Best-README-Template](https://github.com/othneildrew/Best-README-Template) - README structure
- [Typer](https://typer.tiangolo.com/) - CLI framework
- [Rich](https://rich.readthedocs.io/) - Terminal formatting
- Apple Notes reverse engineering community for database structure insights

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[claude-badge]: https://img.shields.io/badge/Claude_Code-cc785c?style=flat&logo=anthropic&logoColor=white
[claude-url]: https://docs.anthropic.com/en/docs/claude-code
[python-shield]: https://img.shields.io/badge/python-3.14+-blue?style=for-the-badge&logo=python&logoColor=white
[python-url]: https://www.python.org/
[python-badge]: https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white
[license-shield]: https://img.shields.io/badge/license-MIT-green?style=for-the-badge
[license-url]: https://github.com/tdemarest/noted/blob/main/LICENSE
[contributors-shield]: https://img.shields.io/github/contributors/tdemarest/noted?style=for-the-badge
[contributors-url]: https://github.com/tdemarest/noted/graphs/contributors
[issues-shield]: https://img.shields.io/github/issues/tdemarest/noted?style=for-the-badge
[issues-url]: https://github.com/tdemarest/noted/issues
[typer-badge]: https://img.shields.io/badge/Typer-009688?style=flat&logo=python&logoColor=white
[typer-url]: https://typer.tiangolo.com/
[rich-badge]: https://img.shields.io/badge/Rich-4B0082?style=flat&logo=python&logoColor=white
[rich-url]: https://rich.readthedocs.io/
