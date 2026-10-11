# Project: Apple Notes Utility

## PROJECT CONTEXT

A Python CLI (`noted`) that works directly with the Apple Notes SQLite database: list,
view, search (FTS5), stats, and export (Markdown, JSON, HTML, PDF, with attachments).
Development operates on a cached copy of the database; write operations are not
implemented yet. See [USAGE.md](USAGE.md) for commands and `uv run noted --help`.

Stack, locked versions, gotchas and daily commands: [docs/tech-stack.md](docs/tech-stack.md).

## Apple Database Structure

Key tables:

- ZICCLOUDSYNCINGOBJECT: notes, folders, attachments
- ZICNOTEDATA: note content; ZDATA is gzip-compressed protobuf (rich text, embedded
  objects, checklists), parsed with betterproto2 (see `src/noted/protobuf.py`)

Column-level detail lives in `docs/apple-notes-*.md` (start with
`apple-notes-storage-reference.md`).

## CRITICAL RULES

- The Apple Notes data location is: ~/Library/Group Containers/group.com.apple.notes
  - The SQLite database is: NoteStore.sqlite
  - The SHM file is: NoteStore.sqlite-shm
  - The WAL file is: NoteStore.sqlite-wal
- Make copies of the sqlite files and never operate on the live versions. The code caches
  the copy in `~/.cache/noted` (`CACHE_DIR` in `src/noted/db.py`):

```python
shutil.copy("NoteStore.sqlite", "/tmp/notes_copy.sqlite")
```

- Use read only mode in development:

```python
# URI mode with read-only flag
conn = sqlite3.connect("file:path/to/db.sqlite?mode=ro", uri=True)
```

- Never truncate data in report output - all text must be visible
- Never use personal identifiable (PII) or sensitive information in documentation,
examples, code comments, etc.

Note: Apple uses Core Data timestamps (seconds since Jan 1, 2001), so you add 978307200 to convert to Unix epoch.

## CODE CONVENTIONS

Tooling (ruff, pyrefly, pytest) and its settings live in `pyproject.toml`; see
[docs/tech-stack.md](docs/tech-stack.md).

- Keep source files to ~1000 lines or less (not enforced: `db.py` and `display.py` currently exceed it and are candidates for splitting). Does not apply to output files like HTML/CSS.
- Write modular, reusable and clean code; prefer simple code over clever complexity
- PEP-8 naming; type hints everywhere, including tests; docstrings (Google style) on all modules, functions, classes and methods
- No star imports (`from foo import *`)
- `pathlib.Path` for file paths (not `os.path`; none used today)
- ISO 8601 dates in output (YYYY-MM-DD; display uses `YYYY-MM-DD HH:MM`)
- Async services and UUID7 ids are aspirations only: no async code or uuid generation exists yet
- Cache lives at `~/.cache/noted` (hardcoded, not XDG-aware); `noted export` defaults to `./notes_export`, not `input/` or `output/`
- **Cryptography** - FIPS-approved and post-quantum ready only; `pqc-check.py` enforces it at commit. Before writing crypto code, check the library's current docs via Ref.
  - Key establishment: **ML-KEM-768/1024** (FIPS 203), or a hybrid such as **X25519MLKEM768** in TLS 1.3. Never RSA, ECDH, X25519 or DH alone.
  - Signatures: **ML-DSA-65/87** (FIPS 204) or **SLH-DSA** (FIPS 205); LMS/XMSS (SP 800-208) for firmware signing. Never new RSA, ECDSA or Ed25519 keys. A classical algorithm is allowed only as one half of a hybrid with the PQC one.
  - Symmetric and hashing: **AES-256-GCM**; **SHA-256/384/512** or **SHA3**; **HMAC-SHA-256+**; passwords via **PBKDF2-HMAC-SHA-256/512** (SP 800-132; bcrypt/scrypt/argon2 aren't FIPS-approved); randomness from `secrets` / `crypto.getRandomValues`. No MD5, SHA-1, DES/3DES, RC4, ChaCha20 or ECB.
  - TLS 1.3 only. JWTs this service issues and verifies itself: HS256+ (or ML-DSA where the library supports it), never `none`.
  - Implementations: a FIPS 140-3 validated module (OpenSSL 3.5+ FIPS provider, AWS-LC) through Python `cryptography` >= 48 (ML-KEM/ML-DSA) or Node `crypto` >= 24.7 (ML-KEM, ML-DSA, SLH-DSA). Never crypto-js, node-forge, pycryptodome, liboqs or pre-standard Kyber/Dilithium.
  - Can't migrate yet (an IdP's RS256 tokens, a partner protocol): add a `.pqc-policy` entry with the reason and an `until=` date, and track the migration in `docs/agent/todo.md`. Python's `hashlib.*(usedforsecurity=False)` marks a non-security digest.
- **Line endings are LF** - `.gitattributes` (`* text=auto eol=lf`) enforces it. Never write CRLF, and never keep a file CRLF because it "was CRLF already"; a CRLF shell script breaks on Linux.

## Working Memory

Project memory is plain files in git - no memory layer. This file holds the stable
rules, stack and architecture. The two files below hold the changing state and are
imported into every session:

@docs/agent/todo.md
@docs/agent/session-log.md

- **After finishing a task** - update `docs/agent/todo.md` (move the item, add what came
  up) and add an entry at the top of `docs/agent/session-log.md`: decisions, dead ends,
  open threads. Skip trivial edits. Commit both with the work.
- **Starting a new major feature** - trim the session log to entries still relevant;
  git keeps the rest.
- **Where things go** - roadmap and tasks: `todo.md`. Session decisions: `session-log.md`.
  Detailed plans: `docs/plans/` (in-flight plans under review may live in Ref Plans,
  see "Docs and Plans - Ref"). Stable rules and gotchas: this file. Serena memories:
  code-structure notes only. Personal preferences: Claude auto-memory, not the repo.

## Zero-Tolerance Quality Gate

**No commit may land with any failure in any stack.** Non-negotiable.

The gate is **detection-based** (`.claude/hooks/precommit-gate.sh`): it runs ruff/pyrefly/pytest for the root
Python package (and any `packages/*` package), and the cryptography check (`pqc-check.py`, see
"Cryptography") over the whole repo, collecting **every** failure at once:

```bash
bash .claude/hooks/precommit-gate.sh --local   # full gate, every present stack
python3 .claude/hooks/pqc-check.py --all      # crypto check alone, with allowed/advisory findings
uv run ruff check . && uv run ruff format --check . \
  && uv run pyrefly check && uv run pytest -n auto -x
```

Enforced two ways - do not bypass either:

1. **Claude Code hook** - `.claude/hooks/precommit-gate.sh` runs as a `PreToolUse` hook on every `Bash` call and gates `git commit` (including `git -C <path> commit`); see `.claude/settings.json`. If any check fails, the commit is blocked.
2. **pre-commit backstop** - `.pre-commit-config.yaml` delegates to the same gate, so even a non-Claude commit runs every present stack's checks.

The gate runs pytest with `-x` (fail fast on the first failing test).

Never use `git commit --no-verify`, never disable hooks, never silence rules without an explicit user decision recorded in code review.

### Fix patterns

When the gate fails, fix the root cause - never silence the rule:

- **Ruff** - `uv run ruff format .` then fix remaining lints.
- **Yield fixtures** - annotate the return as `Iterator[T]` / `AsyncIterator[T]` (from `collections.abc`), not `T`.
- **`asyncio.run(...)`** - pass a `Coroutine`, not a bare `Awaitable`; call an `async def` factory and pass its result.
- **Imports inside functions (PLC0415)** - move them to module top. `# noqa: PLC0415` only with a comment explaining the genuine need (e.g. a circular import).
- **Slow tests** - synthetic/mock data unless the test is marked `@pytest.mark.integration`. Always run via `pytest -n auto`.
- **pqc-check** - replace the algorithm (see "Cryptography"). Only when it can't change yet (a third party's RS256 tokens, an external protocol) add a `.pqc-policy` entry with a reason, and for quantum findings an `until=` date; never edit `pqc-check.py` to pass.

## Code Lookup - Use Serena, Not grep/find

For symbol and file lookup in this repo, use the **Serena MCP server** rather than `grep`, `rg`, or `find`. Serena is LSP-aware and gives accurate symbol-level results.

- Activate the project on first use: `mcp__serena__activate_project`, then `mcp__serena__initial_instructions` to learn the full toolset.
- Lookup tools: `find_symbol`, `find_referencing_symbols`, `find_implementations`, `find_declaration`, `get_symbols_overview`.
- Edit tools: `replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`, `rename_symbol`, `safe_delete_symbol`.
- Diagnostics: `get_diagnostics_for_file`. Memories: `list_memories`, `read_memory`, `write_memory` (code structure only; project state lives in `docs/agent/`).

Fall back to plain text search only for non-source files (logs, configs, raw data).

## Docs and Plans - Ref

Two separate Ref MCP servers (ref.tools), installed at user scope, not in `.mcp.json`:

- **Ref Context** (server `Ref`) - library and API documentation search. When code
  touches a third-party library, framework or API, check its current docs with
  `ref_search_documentation` (name the language and library in the query), then
  `ref_read_url` on the exact result URL. Prefer this over memory or changelogs,
  especially for fast-moving packages, after a lint/type error on a library call, and
  during dependency bumps. Not needed for code that only touches this repo.
- **Ref Plans** (server `RefPlan`) - hosted plan documents that humans review and
  agents read and update. Use it when the user points at a Ref plan or asks to plan in
  Ref: `List` / `Create` to find or start one, `Read` it before implementing, `Edit`
  it to mark tasks done or record a changed approach, `Comments` for open questions,
  `PrLinks` to attach PRs. `ListSkills` / `Skill` load Ref's own planning guidance.
  `LaunchAgent` starts paid external agents (Cursor, Devin, Warp OZ); use it only
  when the user asks. Plans are hosted off-machine: never put secrets in them.
  Settled decisions graduate into `docs/plans/` or this file; the repo keeps the
  long-term record.

## Developer Tooling

All tools below are assumed installed on the system and in Claude.

- **uv** - this repo is a single uv project at the root: `uv sync`; run with `uv run ...`. `uv tool install` puts CLIs in `~/.local` (keep `~/.local/bin` on PATH); `uv tool upgrade --all`.
- **Serena** (MCP) - `serena init`; LSP-aware lookup (above).
- **Ref Context** and **Ref Plans** (MCP, user scope) - library docs and hosted plans (above).

## Git & Branching

- **Conventional Commits** - `type(scope): lowercase imperative description`; types `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `style`, `data`; scope matches the subsystem (see also the Workflow bullet above).
- **Trunk-based** - work directly on `main`; rebase to keep history linear.
- **No Claude attribution** - never add `Co-Authored-By: Claude`, `Generated with Claude Code`, or any other AI-attribution trailer to commits or PRs. Enforced by `attribution: {commit: "", pr: ""}` in `.claude/settings.json`, and backstopped by the `commit-msg` git hook `.claude/hooks/strip-ai-attribution.sh`, which strips such lines from every commit message regardless of settings; do not re-add it manually.

## Commands

```bash
# Install
uv sync

# Commit-gate backstop (once per clone)
uv tool install pre-commit && pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg

# Dev
uv run noted --help

# Checks
uv run ruff check . && uv run ruff format --check . && uv run pyrefly check && uv run pytest -n auto -x

# Gate (every present stack)
bash .claude/hooks/precommit-gate.sh --local
```
