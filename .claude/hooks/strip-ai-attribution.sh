#!/usr/bin/env bash
# commit-msg hook: strips AI attribution from the commit message before git
# records it, independent of any Claude Code `attribution` setting.
#
# Removes (case-insensitive):
#   Co-Authored-By: lines naming Claude or Anthropic (incl. noreply@anthropic.com)
#   "Generated with [Claude Code](...)" lines, with or without a leading emoji
# then trims trailing blank lines left behind.
#
# Wired via .pre-commit-config.yaml (stage commit-msg); git passes the message
# file path as $1. Runs on every commit made in the clone, Claude or not.
set -euo pipefail

msg_file="${1:?usage: strip-ai-attribution.sh <commit-msg-file>}"
[ -f "$msg_file" ] || exit 0

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

awk '
  {
    l = tolower($0)
    if (l ~ /^[[:space:]]*co-authored-by:/ && (l ~ /claude/ || l ~ /anthropic/)) next
    if (l ~ /generated (with|by) .*claude/) next
    lines[++n] = $0
  }
  END {
    while (n > 0 && lines[n] ~ /^[[:space:]]*$/) n--
    for (i = 1; i <= n; i++) print lines[i]
  }
' "$msg_file" > "$tmp"

if ! cmp -s "$msg_file" "$tmp"; then
  cat "$tmp" > "$msg_file"
  echo "strip-ai-attribution: removed AI attribution from the commit message" >&2
fi
