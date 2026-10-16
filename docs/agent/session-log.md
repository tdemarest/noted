# Session Log

Newest first. Imported into every session via `CLAUDE.md`. One entry per finished task:

```
## YYYY-MM-DD - <task>
- Decided: <choice and why>
- Tried and dropped: <approach and why it failed>
- Open: <half-done work, next step>
```

Record what `git log` cannot: decisions, dead ends, open threads. Not a list of changed
files. Trim to the current feature when a new major feature starts (git keeps the
history), and never let it grow past ~15 entries.

<!-- entries below -->

## 2026-10-15 - export --folder implies --all
- Decided: `-f` alone implies `--all`; `-f` with a note ID is an error rather than silently ignored. The filter stays a case-insensitive substring of the full folder path (includes subfolders), so the CLI prints the matched folder paths to expose over-broad matches.
- Decided: a folder filter that matches nothing returns early from `export_all_notes` before creating the output dir, and the CLI exits 1 pointing at `noted list --tree`.
- Open: none.

## 2026-10-10 - export links, anchors and --toc
- Decided: new `outline.py` (keeps display.py from growing); renderers record headings in a shared `Outline` as they emit them, so anchors and TOC never drift. JSON, text and terminal reuse the HTML walk (`collect_headings`). GitHub-style slugs so Markdown `#anchor` links work without emitted ids; note title reserved first. Markdown TOC title is bold text, not a heading, so it does not shift anchors. PDF page numbers via `target-counter` under `@media print` (browsers ignore it).
- Decided: autolink only http(s) and mailto; never in code blocks or headings. Run links with unsafe schemes are now plain text in HTML and Markdown (was a live `javascript:` href).
- Open: index.html for `export --all` (todo Later).

## 2026-10-10 - view list item styling fix
- Decided: trim the styled rich Text in place (`Text.rstrip()`) instead of rebuilding from `str()`, which dropped every span; this also restored the dim strike on checked checklist items.
- Open: none.

## 2026-10-10 - project refresh (project-refresh 1.14.0)
- Decided: betterproto -> betterproto2; adopted project-init tooling and ruff ruleset (line-length 100); fail fast on a missing Notes DB; bundle Roboto for offline PDF; held Python 3.15 (no cp315 wheels for py7zr deps, brotli). Full record: docs/maintenance/2026-10-10-refresh.md.
- Tried and dropped: preloading Homebrew dylibs by absolute path for weasyprint (dyld ignores loaded images for bare names); setting DYLD_FALLBACK_LIBRARY_PATH during the import works.
- Open: split display.py and db.py; local gate patch for a root pyproject.toml until project-init supports it.
