# Tech Stack

Python 3.14 (`requires-python = ">=3.14"`; no `.python-version` file, `uv run python` resolves to 3.14.7). Package manager: uv (not pip). Build backend: hatchling, src layout (`src/noted`), entry point `noted = noted.cli:app`.

## Runtime dependencies (locked versions from uv.lock)

| Package | Locked | Used for | Gotchas |
|---|---|---|---|
| typer | 0.27.3 | CLI commands and options (`cli.py`) | Vendors click, so there is no separate `click` package; do not import click. Option/Argument defaults are whitelisted in ruff B008 settings. |
| rich | 15.0.0 | Terminal tables and output (`display.py`) | Raw JSON/HTML/Markdown goes to stdout via print (T201 ignored in `cli.py`) because Rich would mangle markup. |
| loguru | 0.7.3 | Logging (`cli.py` configures stderr sinks with `colorize=True`) | `logger.remove()` then re-add per run; WARNING level unless `--debug`. |
| betterproto2 | 0.10.0 | Protobuf parsing of note content (`protobuf.py`, `tables.py`) | Pre-1.0, API may shift. Unset message fields are `None`, not empty messages. Replaces the old betterproto. |
| py7zr | 1.1.3 | 7z archive creation for exports (`attachments.py`) | None known. |
| weasyprint | 70.0 | HTML to PDF export | On macOS with uv-managed Python needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` so it finds Pango/Cairo. |

## Dev dependencies (group `dev`)

| Package | Locked | Used for | Gotchas |
|---|---|---|---|
| ruff | 0.17.0 | Lint and format (line length 100, py314, pydocstyle google, rules F E W I N UP B A SIM T20 RUF D ANN) | Also formats Python code blocks inside Markdown files. `.claude` is excluded. |
| pyrefly | 1.3.2 | Type checking (`src`, `tests`) | Zero warnings required by the gate. |
| pytest | 9.1.1 | Tests in `tests/` | `addopts = "-n auto"`; markers `slow`, `integration`. |
| pytest-xdist | 3.8.0 | Parallel test runs | Tests must be isolated; use synthetic data unless marked integration. |

## Daily commands

```bash
uv sync                      # install / update the environment
uv run noted --help          # CLI entry point
uv run ruff format . && uv run ruff check .
uv run pyrefly check
uv run pytest -n auto -x
uvx deptry .                # unused/missing dependencies ([tool.deptry] in pyproject.toml)
bash .claude/hooks/precommit-gate.sh --local   # full commit gate
python3 .claude/hooks/pqc-check.py --all       # crypto check alone
```

PDF output is on `view` (`--pdf` with `-o`). On macOS the uv-managed Python does not search Homebrew libraries, so `import weasyprint` fails on `libgobject-2.0-0` without the path:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run noted view 42 --pdf -o
```
