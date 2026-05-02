#!/usr/bin/env bash
# Lock 5 from docs/inter-bot-protocols.md — fail CI if any Python source
# line both invokes a code-execution primitive AND mentions a council
# message variable on the same line. The two together strongly suggest
# we're about to exec content sourced from a transcript / Telegram /
# user input.
#
# Tune by editing the two regex sets below. Keep the filter conservative;
# the goal is to catch new violations, not produce drift on existing
# patterns.

set -euo pipefail

if ! command -v rg >/dev/null 2>&1; then
  echo "[lint-no-exec] ripgrep (rg) is required but not installed" >&2
  echo "[lint-no-exec] install: brew install ripgrep   |   apt: apt-get install ripgrep" >&2
  exit 2
fi

EXEC_RE='(eval|exec|subprocess\.|Process\(|os\.system|sh -c)'
INPUT_RE='(text|message|transcript)'

# Two-stage filter: first find lines mentioning an exec primitive, then
# keep only those that also mention an inbound-message variable.
hits="$(rg -n "$EXEC_RE" --type py 2>/dev/null | rg "$INPUT_RE" || true)"

if [ -n "$hits" ]; then
  echo "[lint-no-exec] FAIL — possible exec-of-message-content (Lock 5)" >&2
  echo "$hits" >&2
  echo "" >&2
  echo "[lint-no-exec] If this is a false positive, refactor to separate" >&2
  echo "[lint-no-exec] the exec call from the message variable on the line," >&2
  echo "[lint-no-exec] or update the regex sets in this script." >&2
  exit 1
fi

echo "[lint-no-exec] clean"
