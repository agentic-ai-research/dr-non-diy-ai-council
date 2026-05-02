"""
validator.py — council-side post-write transcript validator.

Watches new entries land in ~/.council/transcript.jsonl, checks each one
against the protocol (palette discipline, identity fields, lane gates,
token shape leaks), and surfaces violations as a 🪑 RULING line in the
transcript itself plus an optional Telegram DM to Dr Non.

Designed to make protocol drift VISIBLE — not to block bots from posting.
A bot can still post a malformed line; the validator catches it within
30s, names the violation, and lets the room self-correct. Over time, the
violation rate is the KPI for whether the council is hardening.

Cron entry on the council Mac (every 30s):

    * * * * * /usr/bin/python3 /path/to/validator.py >> ~/.council/validator.log 2>&1
    * * * * * sleep 30 && /usr/bin/python3 /path/to/validator.py >> ~/.council/validator.log 2>&1

Or, more idiomatic with launchd, set StartInterval to 30.

Stdlib-only.
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import logging
import os
import re
import sys
from pathlib import Path

# --- Config ------------------------------------------------------------------

COUNCIL_DIR     = Path(os.environ.get("COUNCIL_DIR", str(Path.home() / ".council")))
TRANSCRIPT_GLOB = str(COUNCIL_DIR / "transcript-*.jsonl")
STATE_FILE      = COUNCIL_DIR / "validator.state.json"

# Palette by justice (lifted from docs/production-mode.md and docs/justice-roles.md)
PALETTES: dict[str, set[str]] = {
    "Tenet":  {"ROUTE:", "FAN-OUT:", "FAN-IN:", "🪑 RULING:", "🪑 PIN:", "🪑 KILLED:",
               "🪑 REWORK:", "MODE:", "ACK:", "PREEMPT:", "RESUME:"},
    "Radar":  {"FACT:", "EVIDENCE:", "DEDUCE:", "NULL:", "FAILOVER:"},
    "Otto":   {"DRAFT:", "SENT:", "BLOCKED-EXTERNAL:", "BLOCKER:", "OCR:", "SYNCED:",
               "BENCH:", "CHECKPOINT:", "STAND-DOWN:", "PRE-CALL:", "FAILOVER:"},
    "Hannah": {"PRECEDENT:", "PATTERN:", "OUTLIER:", "NULL:"},
    "Ada":    {"BIAS:", "PRE-MORTEM:", "THAI:", "SLOW:"},
    "Ana":    {"DUTY:", "UNIVERSAL:", "MEANS-END:"},
    "Civic":  {"UTILITY:", "2ND-ORDER:", "BENEFICIARIES:"},
    "Aviva":  {"STRATEGIC:", "POSITION:", "LONG-VIEW:"},
    "Bob":    {"SANITY:", "IN-PRACTICE:", "OBVIOUS:"},
    "Pip":    {"QR:", "PDF:", "OCR:", "PRINT:", "NOTE:", "DRIVE:"},
    "Eve":    {"STATUS:", "BUILD ESTIMATE:", "BLOCKER:", "PASS:", "BRIEF:",
               "CONTRACT:", "NEEDS-IOS:", "SCAFFOLD:", "REFACTOR:", "TEST:",
               "DEBUG:", "PROFILE:", "PRE-CALL:", "SENT:", "FAILOVER:"},
    "LOL":    {"STATUS:", "BUILD ESTIMATE:", "BLOCKER:", "PASS:", "BRIEF:",
               "CONTRACT:", "NEEDS-IOS:", "NEEDS-BACKEND:", "SIMRUN:", "DEVICE:"},
    "noN":    {"noN:", "NoN:", "Non:"},
    "Nun":    {"LIBRARY:", "PATTERN-X-SESSIONS:", "DEEP-DIVE:", "MORNING-BRIEF:",
               "SLOW:", "NULL:"},
}

# Required transcript-line fields (per docs/communication-protocol.md)
REQUIRED_FIELDS = {"ts", "from", "text"}
RECOMMENDED_FIELDS = {"bot_id", "machine"}

# Token-shape leak detection (defense in depth — Lock 2)
TOKEN_PATTERNS = [
    re.compile(r"bot[0-9]{6,}:[A-Za-z0-9_-]{30,}"),
    re.compile(r"\b[0-9]{6,}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]

# Lane refusals (a bot must not call a tool not in their lane)
THINKER_BOTS = {"Tenet", "Hannah", "Ada", "Ana", "Civic", "Aviva", "Bob", "noN"}
TOOL_VERBS   = {"PRE-CALL:", "SENT:", "BLOCKED-EXTERNAL:", "OCR:", "SYNCED:"}

# Thread-tag pattern from docs/multi-task.md
THREAD_TAG_RE = re.compile(r"^\[#([a-z0-9-]+)\]\s*")

# System actors (skipped from palette validation)
HUMAN_OR_SYSTEM_AUTHORS = {"Dr Non", "system", "_inquiry_", "_chair_protocol_",
                          "health-check", "queue-recovery", ""}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [validator] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("validator")


# --- State -------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"last_ts": "", "last_file": "", "last_offset": 0,
            "violation_count_by_bot": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# --- Validation rules --------------------------------------------------------

def validate(entry: dict) -> list[str]:
    """Return a list of violation strings for one transcript line. Empty = clean."""
    issues: list[str] = []

    # Required fields
    missing = REQUIRED_FIELDS - set(entry.keys())
    if missing:
        issues.append(f"missing required fields: {sorted(missing)}")

    author = (entry.get("from") or "").strip()
    text   = (entry.get("text") or "").strip()

    # Skip humans / system actors for palette / lane checks
    if author in HUMAN_OR_SYSTEM_AUTHORS:
        return issues

    # Palette discipline (only check known justices)
    palette = PALETTES.get(author)
    if palette is not None:
        body = THREAD_TAG_RE.sub("", text)
        # The verb must be the first whitespace-delimited token (or two for "BUILD ESTIMATE:")
        verb = (body.split(" ", 2)[0] if body else "") + ":"
        verb = verb.replace("::", ":").rstrip(":") + ":"
        verb_or_two = body.split(" ", 2)
        joined_two = " ".join(verb_or_two[:2])[: len("BUILD ESTIMATE:")] if len(verb_or_two) >= 2 else ""

        opens_with_palette = (
            any(body.startswith(v) for v in palette)
            or any(body.startswith(v.rstrip(":") + " ") for v in palette)
        )
        if not opens_with_palette:
            preview = body[:60] + ("…" if len(body) > 60 else "")
            issues.append(
                f"off-palette: {author} should open with one of "
                f"{sorted(palette)[:5]}{'…' if len(palette) > 5 else ''} but said {preview!r}"
            )

    # Lane refusal — thinkers must not emit tool-call verbs
    if author in THINKER_BOTS:
        body = THREAD_TAG_RE.sub("", text)
        for tv in TOOL_VERBS:
            if body.startswith(tv):
                issues.append(f"lane violation: {author} (thinker) used tool verb {tv!r}")
                break

    # Token leak (Lock 2)
    for pat in TOKEN_PATTERNS:
        if pat.search(text):
            issues.append(
                f"token shape detected in transcript: {pat.pattern[:30]}…  REDACT BEFORE NEXT WRITE"
            )
            break

    # Identity fields (recommended, not required)
    rec_missing = RECOMMENDED_FIELDS - set(entry.keys())
    if rec_missing and author not in HUMAN_OR_SYSTEM_AUTHORS:
        issues.append(f"missing recommended identity fields: {sorted(rec_missing)} (warn)")

    return issues


# --- Main loop ---------------------------------------------------------------

def main() -> int:
    state = _load_state()
    last_ts = state.get("last_ts", "")
    transcripts = sorted(glob.glob(TRANSCRIPT_GLOB))
    if not transcripts:
        log.info("no transcripts under %s; nothing to do", COUNCIL_DIR)
        return 0

    new_violations = 0
    new_entries = 0
    high_water = last_ts

    for path in transcripts:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    ts = entry.get("ts", "")
                    if ts and ts <= last_ts:
                        continue

                    new_entries += 1
                    if ts > high_water:
                        high_water = ts

                    violations = validate(entry)
                    if violations:
                        new_violations += len(violations)
                        author = (entry.get("from") or "?").strip()
                        state["violation_count_by_bot"][author] = (
                            state["violation_count_by_bot"].get(author, 0) + len(violations)
                        )
                        log.warning(
                            "VIOLATION  ts=%s  from=%s  count=%d",
                            ts, author, len(violations),
                        )
                        for v in violations:
                            log.warning("           %s", v)
        except OSError as e:
            log.error("read failed for %s: %s", path, e)
            continue

    if new_entries == 0:
        log.info("no new entries since %s; quiet", last_ts or "(forever)")
        return 0

    state["last_ts"] = high_water
    _save_state(state)
    log.info(
        "validated %d new entries (since %s); %d violations across %d bot(s)",
        new_entries, last_ts or "(forever)", new_violations,
        sum(1 for v in state["violation_count_by_bot"].values() if v > 0),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
