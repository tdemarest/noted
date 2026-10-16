# Todo

Roadmap and active work. Imported into every session via `CLAUDE.md`, so keep it short:
one line per item, link to `docs/plans/<plan>.md` for detail.

## Now

- TBD

## Next

- Split `src/noted/display.py` (~2400 lines) and `src/noted/db.py` (~1300) under the ~1000-line convention

## Later

- `export --all`: generate an `index.html` linking every exported note (index.json only today)

## Recently done

Last ~10 items, newest first. Drop older ones; `git log` keeps the full history.

- `noted export -f <folder>` works without `--all`; lists matched folders, errors on no match
- Export links: bare-URL autolinks, heading anchors, `--toc` for every format, unsafe run-link fix
- `noted view` list items keep run styles and checked-item strike style
- Project refresh 2026-10-10 complete (docs/maintenance/2026-10-10-refresh.md)
- Display escaping, format-flag conflicts, offline PDF with bundled Roboto (57c1d76)
- Adopted project-init tooling during the 2026-10-10 refresh (b75a407)
