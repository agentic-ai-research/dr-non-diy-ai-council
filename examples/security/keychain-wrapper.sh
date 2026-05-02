#!/usr/bin/env bash
# keychain-wrapper.sh — read a per-bot credential from macOS Keychain, then
# exec the real binary with that credential set as a single env var.
#
# Why this exists:
#   The council's Lock 3 says secrets live in Keychain, never in launchd
#   plist `EnvironmentVariables`, never in shared `.env`. This wrapper is
#   the indirection that makes that practical: the plist references this
#   script, the script reads the secret at boot, and the bot binary
#   inherits one env var from the wrapper's own process — never from disk.
#
# Usage in a launchd plist:
#
#   <key>ProgramArguments</key>
#   <array>
#     <string>/Users/YOU/.council/lib/keychain-wrapper.sh</string>
#     <string>council-eve-telegram</string>      <!-- keychain service name -->
#     <string>EVE_TG_TOKEN</string>              <!-- env var name to set   -->
#     <string>/usr/local/bin/eve-coder</string>  <!-- the real binary       -->
#     <!-- any args the binary needs, follow as additional <string>s -->
#   </array>
#
# What is NOT in scope:
#   * This wrapper does NOT modify the binary's behavior in any way.
#   * The token is exported as an env var visible to the child process
#     (and to anything else running as the same user that can read
#     /proc/<pid>/environ — same trust model as everything else on the
#     Mac). For tighter isolation, use a domain-socket-based broker.

set -euo pipefail

if [ "$#" -lt 3 ]; then
    cat >&2 <<'USAGE'
keychain-wrapper.sh: not enough args.

usage:  keychain-wrapper.sh <keychain-service-name> <env-var-name> <binary> [args...]

example:
    keychain-wrapper.sh council-eve-telegram EVE_TG_TOKEN /usr/local/bin/eve-coder --config /Users/you/.eve/config.yml
USAGE
    exit 2
fi

SERVICE="$1"; shift
ENV_VAR_NAME="$1"; shift

# Read the secret. -w prints the password to stdout; nothing else.
# `2>/dev/null` swallows the harmless stderr message Keychain prints
# on access; we'll detect missing items via the empty-string check below.
SECRET="$(security find-generic-password -a "$USER" -s "$SERVICE" -w 2>/dev/null || true)"

if [ -z "$SECRET" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') keychain-wrapper: no secret found for service=$SERVICE account=$USER" >&2
    echo "  fix: security add-generic-password -a \"\$USER\" -s \"$SERVICE\" -w -U" >&2
    exit 1
fi

# Export under the requested env var name; immediately unset our own
# local copy so it's not visible in this script's own environment any
# longer than necessary.
export "${ENV_VAR_NAME}=${SECRET}"
SECRET=""
unset SECRET

# Hand off to the real binary. `exec` replaces this shell process so
# there's no extra layer of process isolation lost; the binary becomes
# the launchd-managed process.
exec "$@"
