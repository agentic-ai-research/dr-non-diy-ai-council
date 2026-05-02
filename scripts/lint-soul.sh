#!/usr/bin/env bash
# lint-soul.sh — structural validator for SOUL.md files.
#
# A SOUL.md drifts when it stops asserting the bot's identity, palette, lane,
# and refusals clearly. This script enforces a minimum schema so a bot
# without a working SOUL can't merge.
#
# Pass any number of SOUL.md paths as args. Without args, scans every
# *.SOUL.md / SOUL*.md under examples/identity/ and examples/souls/.
#
# Required structure (each level is a header check):
#   1. Title (# heading)
#   2. ## Identity              — names the justice + handle
#   3. ## Palette OR contains a verb table
#   4. ## Refusals OR a "what NOT to do" / "lane" section
#
# Exits non-zero on any violation. Drop into CI alongside lint-no-exec.sh.

set -euo pipefail

CHECK_PATHS=()
if [ "$#" -eq 0 ]; then
    while IFS= read -r f; do CHECK_PATHS+=("$f"); done < <(
        find examples/identity examples/souls 2>/dev/null \
             -type f \( -name "*SOUL*.md" -o -name "*soul*.md" \) \
        | sort -u
    )
else
    CHECK_PATHS=("$@")
fi

if [ "${#CHECK_PATHS[@]}" -eq 0 ]; then
    echo "[lint-soul] no SOUL files found to lint" >&2
    exit 0
fi

echo "[lint-soul] checking ${#CHECK_PATHS[@]} file(s)" >&2
violations=0

for f in "${CHECK_PATHS[@]}"; do
    [ -f "$f" ] || { echo "[lint-soul] not a file: $f" >&2; violations=$((violations+1)); continue; }

    # Skip template files (they're partials by design)
    case "$(basename "$f")" in
        *template*|*TEMPLATE*) echo "[lint-soul] skip template: $f" >&2; continue ;;
    esac

    # 1. Has a level-1 title
    if ! grep -qE "^# " "$f"; then
        echo "[lint-soul] FAIL  $f  — missing level-1 title" >&2
        violations=$((violations+1))
    fi

    # 2. Has an Identity section that names the justice
    if ! grep -qiE "^##[[:space:]]+(Identity|You are)" "$f"; then
        echo "[lint-soul] FAIL  $f  — no '## Identity' section (or '## You are')" >&2
        violations=$((violations+1))
    fi

    # 3. Has a palette declaration (table OR explicit Palette section)
    if ! grep -qiE "^##[[:space:]]+(Palette|Your palette|Verbs|Grammar)" "$f" \
       && ! grep -qE "^\|.*Verb.*\|" "$f"; then
        echo "[lint-soul] FAIL  $f  — no palette declared (## Palette / ## Verbs / verb table)" >&2
        violations=$((violations+1))
    fi

    # 4. Has refusals / lane / NOT-do section
    if ! grep -qiE "^##[[:space:]]+(Refus|Lane|What.*NOT|You do NOT|Boundary)" "$f"; then
        echo "[lint-soul] FAIL  $f  — no refusals / lane / 'what you do NOT do' section" >&2
        violations=$((violations+1))
    fi

    # 5. Names a Telegram handle (the @-prefixed symbol)
    if ! grep -qE "@[A-Za-z][A-Za-z0-9_]+_bot" "$f"; then
        echo "[lint-soul] WARN  $f  — no Telegram @handle named (recommended for routing)" >&2
        # warn-only, not a fail
    fi

    echo "[lint-soul] ok    $f"
done

if [ "$violations" -gt 0 ]; then
    echo "" >&2
    echo "[lint-soul] FAIL — $violations violation(s) across ${#CHECK_PATHS[@]} file(s)" >&2
    exit 1
fi
echo "[lint-soul] clean"
