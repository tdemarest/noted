#!/usr/bin/env bash
# Canonical multi-stack commit gate - shipped VERBATIM in every *-template repo
# (project-template/cli, fastapi-template, react-template, fullstack-template).
#
# It DETECTS which stacks are present and runs only their checks, collecting
# EVERY failure before blocking:
#   packages/web                   -> biome, tsc, vitest
#   packages/<name>/pyproject.toml -> ruff (+format), pyrefly, pytest   (api, cli, ...)
#   always (whole repo)            -> pqc-check.py: FIPS-approved, PQC-ready crypto only
#
# Detection-based + a loop over Python packages means adding a stack (web, a new
# FastAPI api, a Typer cli, ...) EXTENDS the gate automatically - no edits needed.
# That is what lets the React / FastAPI / CLI skills augment one another's
# projects instead of fighting over a hand-written gate.
#
# Modes:
#   (hook)    reads PreToolUse JSON on stdin; only gates `git commit`
#   --local   run all present checks now (used by `bun run gate` / pre-commit)
#
# Exit codes: 0 pass (or non-commit / no stacks) . 2 block
#
# Hook mode runs before EVERY Bash tool call, so the pass-through path is kept
# cheap: a substring test on the raw payload rejects most calls before any JSON
# parsing happens.

set -uo pipefail

LOCAL=0
[[ "${1:-}" == "--local" ]] && LOCAL=1

if [[ $LOCAL -eq 0 ]]; then
  input="$(cat)"
  case "$input" in
    *commit*) ;;
    *) exit 0 ;;
  esac

  if command -v jq >/dev/null 2>&1; then
    command="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)"
  else
    command="$(
      printf '%s' "$input" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    pass
' 2>/dev/null
    )"
  fi

  # Gate `git commit`, including forms with global options between `git` and
  # the subcommand (`git -C <path> commit`, `git -c k=v commit`). Anchor on a
  # command boundary so `git commit-tree`, `--grep=commit` and `echo commit`
  # pass through. Ambiguity fails closed: the gate runs rather than being skipped.
  git_commit_re='(^|[;&|(]|[[:space:]])git[[:space:]]+([^[:space:]]+[[:space:]]+)*commit([[:space:]]|$)'
  if ! [[ "$command" =~ $git_commit_re ]]; then
    exit 0
  fi
fi

# Resolve the repo root. $CLAUDE_PROJECT_DIR is set by Claude Code for hooks;
# outside Claude (pre-commit backstop, manual --local) fall back to git, then to
# the script's own location. Never trust $PWD: a subdirectory cwd would find no
# packages and silently pass.
root="${CLAUDE_PROJECT_DIR:-}"
[[ -z "$root" ]] && root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -z "$root" ]] && root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$root" || { printf 'commit gate: cannot cd to %s\n' "$root" >&2; exit 2; }

# pytest-xdist workers plus temp files can exhaust the macOS default soft FD
# cap of 256 ("OSError: [Errno 24] Too many open files").
ulimit -n 4096 2>/dev/null || true

declare -a failures=()
ran_any=0
section() { printf '\n- %s\n' "$1" >&2; }
run() {
  local name="$1"
  shift
  if ! "$@"; then failures+=("$name"); fi
}

# -- Cryptography: FIPS-approved, post-quantum ready (whole repo, every stack) --
if [[ -f .claude/hooks/pqc-check.py ]]; then
  ran_any=1
  section "crypto . FIPS + PQC"
  run "crypto:pqc" python3 -I .claude/hooks/pqc-check.py --root "$root"
fi

# -- Web stack (bun + Vite) --
if [[ -d packages/web ]]; then
  ran_any=1
  section "web . biome"
  run "web:biome" bunx @biomejs/biome check .
  section "web . tsc"
  run "web:tsc" bun --filter web typecheck
  section "web . vitest"
  run "web:vitest" bun --filter web test
fi

# -- Every Python package (uv): api, cli, ... - detected by pyproject.toml --
# Local patch: also cover a root pyproject.toml (project-init follow-up).
for pyproject in pyproject.toml packages/*/pyproject.toml; do
  [[ -e "$pyproject" ]] || continue
  pkg="$(dirname "$pyproject")"
  name="$(basename "$pkg")"
  [[ "$pkg" == "." ]] && name="root"
  ran_any=1
  section "$name . ruff + format"
  run "$name:ruff" bash -c "cd '$pkg' && uv run ruff check . && uv run ruff format --check ."
  section "$name . pyrefly"
  if ! grep -q '^\[tool\.pyrefly\]' "$pyproject"; then
    printf '... warning: %s has no [tool.pyrefly] section - pyrefly runs its lenient basic preset\n' "$pyproject" >&2
  fi
  run "$name:pyrefly" bash -c "cd '$pkg' && uv run pyrefly check"
  section "$name . pytest"
  run "$name:pytest" bash -c "cd '$pkg' && uv run pytest -n auto -x -q"
done

if [[ $ran_any -eq 0 ]]; then
  printf '... commit gate: no pqc-check.py, packages/web, pyproject.toml or packages/*/pyproject.toml under %s - nothing to check\n' "$root" >&2
  exit 0
fi

if ((${#failures[@]} > 0)); then
  printf '\nx commit blocked - %d check(s) failed: %s\n' "${#failures[@]}" "${failures[*]}" >&2
  exit 2
fi

printf '\nok commit gate passed\n' >&2
exit 0
