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

## 2026-10-10 - project refresh (project-refresh 1.14.0)
- Decided: betterproto -> betterproto2; adopted project-init tooling and ruff ruleset (line-length 100); fail fast on a missing Notes DB; bundle Roboto for offline PDF; held Python 3.15 (no cp315 wheels for py7zr deps, brotli). Full record: docs/maintenance/2026-10-10-refresh.md.
- Tried and dropped: preloading Homebrew dylibs by absolute path for weasyprint (dyld ignores loaded images for bare names); setting DYLD_FALLBACK_LIBRARY_PATH during the import works.
- Open: split display.py and db.py; local gate patch for a root pyproject.toml until project-init supports it.
