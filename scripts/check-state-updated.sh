#!/usr/bin/env bash
#
# CI guard: fail unless STATE.md is among the changed files of a PR/commit.
# STATE.md is the single source of truth for progress — every step must touch it.
#
# Input (first match wins):
#   $CHANGED_FILES  newline-separated list (used in CI from `git diff --name-only`)
#   $1              same list passed as a single argument (supports `\n` escapes)
#
# Exit 0 if STATE.md is present in the list, else exit 1 with a message on stderr.

set -euo pipefail

input="${CHANGED_FILES:-${1:-}}"

if printf '%b\n' "$input" | grep -qxF 'STATE.md'; then
  exit 0
fi

echo "STATE.md not updated: STATE.md must be among the changed files in this change." >&2
exit 1
