"""
Reflection cron job — turns transcript pins AND Dr Non's supervisor tags into
per-bot exemplar files.

Two parallel mining streams:

  1. PIN MINING (the original; from docs/learning-loops.md):
     Reads transcript pins (🪑 PIN: / 🪑 KILLED: / 🪑 REWORK: / 🪑 RULING:).
     Each justice that contributed gets scored:
       good   — display name cited in pin/ruling text
       bad    — pin/ruling explicitly overrules / rejects this bot
       mixed  — contributed but not cited
     Writes ~/.council/exemplars/<bot_id>/<outcome>/<thread-id>.json.
     Marker:  ~/.council/exemplars/.last-run

  2. SUPERVISOR TAG MINING (added — supervised-training signal):
     Reads Dr Non's tags of the form
         "@<bot> good — <reason>"
         "@<bot> bad  — <reason>"
     in any council message. The em-dash (—) or two hyphens (--) separate
     the verdict from the reason. Case-insensitive on good/bad. Multiple
     tags in one message are all captured.
     For each tag, finds the target bot's most recent prior contribution in
     the same thread (within ≤24h) and writes that as an exemplar with
     `source: "supervisor"` under
         ~/.council/exemplars/<bot_id>/<good|bad>/by-supervisor/<id>.json
     Supervisor exemplars carry weight=2.0 so retrieval ranks them above
     outcome-mined ones — Dr Non's explicit feedback is the strongest signal.
     Marker:  ~/.council/exemplars/.last-tag-run

Stdlib-only. No retraining, no embeddings.

Cron entry on the council Mac (every 5 minutes):
  */5 * * * * /usr/bin/python3 /path/to/reflect.py >> ~/.council/reflect.log 2>&1
"""

from __future__ import annotations

import datetime as _dt
import glob
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

# --- Config ------------------------------------------------------------------

COUNCIL_DIR        = Path(os.environ.get("COUNCIL_DIR", str(Path.home() / ".council")))
EXEMPLARS_DIR      = COUNCIL_DIR / "exemplars"
LAST_RUN_FILE      = EXEMPLARS_DIR / ".last-run"          # pin-mining marker
LAST_TAG_RUN_FILE  = EXEMPLARS_DIR / ".last-tag-run"      # supervisor-tag marker
SURROUNDING_N      = 5     # lines of context kept with each exemplar
MAX_TEXT_LEN       = 1500  # mirrors transcript schema

PIN_PREFIXES       = ("🪑 PIN:", "🪑 KILLED:", "🪑 REWORK:", "🪑 RULING:")
HUMAN_AUTHORS      = {"Dr Non", "system", ""}     # not scored as bots

# Dr Non's display name on transcript lines. Tags are only mined from his
# messages — Peter's feedback or another bot's "@x good" don't count.
SUPERVISOR_AUTHOR  = "Dr Non"

# Pattern for supervisor tags. Matches:
#   @<bot> good — <reason>     (em-dash)
#   @<bot> good -- <reason>    (two hyphens; ASCII-friendly fallback)
#   @<bot> good - <reason>     (single hyphen, also accepted)
# Case-insensitive on the verdict; bot name is captured raw and matched
# case-insensitively when locating the target contribution.
SUPERVISOR_TAG_RE  = re.compile(
    r"@([A-Za-z][A-Za-z0-9_]+)\s+(good|bad)\s*(?:—|--|-)\s*([^\n@]+?)(?=\s*(?:@\w|$))",
    re.IGNORECASE,
)

# How far back to look for the target bot's most-recent contribution before
# the supervisor tag. 24h is generous; the tag should usually be a direct
# response within minutes.
TAG_LOOKBACK_HOURS = 24

OVERRULE_PATTERNS = [
    re.compile(r"\boverrul(e[ds]?|ing)\b", re.IGNORECASE),
    re.compile(r"\bruled against\b", re.IGNORECASE),
    re.compile(r"\brejected?\b", re.IGNORECASE),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [reflect] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("reflect")

# --- Helpers -----------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _all_transcript_entries() -> list[dict[str, Any]]:
    """Read all daily transcript files, sorted by ts."""
    entries: list[dict[str, Any]] = []
    pattern = str(COUNCIL_DIR / "transcript-*.jsonl")
    for path in sorted(glob.glob(pattern)):
        entries.extend(_read_jsonl(Path(path)))
    entries.sort(key=lambda e: e.get("ts", ""))
    return entries


def _read_last_run() -> str:
    if not LAST_RUN_FILE.exists():
        return ""
    try:
        return LAST_RUN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_last_run(ts: str) -> None:
    EXEMPLARS_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(ts + "\n", encoding="utf-8")


def _is_pin(entry: dict[str, Any]) -> bool:
    text = (entry.get("text") or "").lstrip()
    return text.startswith(PIN_PREFIXES)


def _thread_id(pin_entry: dict[str, Any], first_contrib_ts: str) -> str:
    seed = (pin_entry.get("ts", "") + "|" + first_contrib_ts).encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:12]


def _score(bot_name: str, pin_text: str) -> str:
    """Score this bot's contribution against the pin text. Fuzzy v1."""
    if not bot_name or bot_name in HUMAN_AUTHORS:
        return "mixed"
    name_re = re.compile(rf"\b{re.escape(bot_name)}\b", re.IGNORECASE)
    name_in_pin = bool(name_re.search(pin_text))
    overruled = any(p.search(pin_text) for p in OVERRULE_PATTERNS)
    if name_in_pin and overruled:
        return "bad"
    if name_in_pin:
        return "good"
    return "mixed"


def _safe_name(s: str) -> str:
    """Keep filenames sane: lowercase, alnum + dash, max 32 chars."""
    s = re.sub(r"[^a-z0-9_-]+", "-", (s or "unknown").lower()).strip("-")
    return (s or "unknown")[:32]


# --- Core --------------------------------------------------------------------

def find_threads(entries: list[dict[str, Any]], since_ts: str) -> list[dict[str, Any]]:
    """Return list of threads {pin, contributions} where pin.ts > since_ts."""
    threads: list[dict[str, Any]] = []
    n = len(entries)
    for i, entry in enumerate(entries):
        if not _is_pin(entry):
            continue
        if entry.get("ts", "") <= since_ts:
            continue

        # Walk back to the most recent human/system message — that's the
        # thread's start. Cap at 30 lines back so a quiet day doesn't
        # accidentally swallow the previous thread.
        start = max(0, i - 30)
        for j in range(i - 1, start - 1, -1):
            author = (entries[j].get("from") or "").strip()
            if author in HUMAN_AUTHORS:
                start = j
                break

        contributions = entries[start + 1 : i]  # exclusive of the pin
        if not contributions:
            continue
        threads.append({"pin": entry, "contributions": contributions, "ctx_start": start})
    return threads


def write_exemplars(thread: dict[str, Any]) -> int:
    pin = thread["pin"]
    pin_text = pin.get("text") or ""
    contributions = thread["contributions"]
    if not contributions:
        return 0

    first_ts = contributions[0].get("ts", "")
    tid = _thread_id(pin, first_ts)
    written = 0

    # Group contributions per bot — the latest line per bot is the canonical
    # exemplar; we still keep the count of turns in the metadata.
    by_bot: dict[str, list[dict[str, Any]]] = {}
    for c in contributions:
        author = (c.get("from") or "").strip()
        if author in HUMAN_AUTHORS:
            continue
        by_bot.setdefault(author, []).append(c)

    for bot_name, lines in by_bot.items():
        bot_id = (lines[-1].get("bot_id") or _safe_name(bot_name)).strip() or _safe_name(bot_name)
        bot_id = _safe_name(bot_id)
        outcome = _score(bot_name, pin_text)

        canonical = lines[-1]
        record = {
            "thread_id": tid,
            "scored_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "outcome":   outcome,
            "bot_name":  bot_name,
            "bot_id":    bot_id,
            "pin": {
                "ts":   pin.get("ts", ""),
                "from": pin.get("from", ""),
                "text": (pin_text or "")[:MAX_TEXT_LEN],
            },
            "contribution": {
                "ts":         canonical.get("ts", ""),
                "text":       (canonical.get("text") or "")[:MAX_TEXT_LEN],
                "turn_count": len(lines),
            },
            "surrounding": [
                {
                    "ts":   e.get("ts", ""),
                    "from": e.get("from", ""),
                    "text": (e.get("text") or "")[:400],
                }
                for e in contributions[-SURROUNDING_N:]
            ],
        }

        out_dir = EXEMPLARS_DIR / bot_id / outcome
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{tid}.json"
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    return written


# --- Supervisor-tag mining (the supervised-training signal) ------------------

def _read_last_tag_run() -> str:
    if not LAST_TAG_RUN_FILE.exists():
        return ""
    try:
        return LAST_TAG_RUN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_last_tag_run(ts: str) -> None:
    EXEMPLARS_DIR.mkdir(parents=True, exist_ok=True)
    LAST_TAG_RUN_FILE.write_text(ts + "\n", encoding="utf-8")


def find_supervisor_tags(entries: list[dict[str, Any]],
                          since_ts: str) -> list[dict[str, Any]]:
    """Scan Dr Non's messages for `@<bot> good|bad — <reason>` tags.

    Returns one record per matched tag with the resolved target contribution.
    Skips tags whose target bot has no recent prior contribution (within the
    lookback window).
    """
    tags: list[dict[str, Any]] = []
    if not entries:
        return tags

    # Index entries by author for fast "most-recent contribution before T" lookup.
    by_author: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        author = (e.get("from") or "").strip()
        if not author or author in HUMAN_AUTHORS:
            continue
        by_author.setdefault(author.lower(), []).append(e)

    for entry in entries:
        if (entry.get("from") or "").strip() != SUPERVISOR_AUTHOR:
            continue
        ts = entry.get("ts", "")
        if ts and ts <= since_ts:
            continue
        text = entry.get("text") or ""
        for m in SUPERVISOR_TAG_RE.finditer(text):
            target_name_raw = m.group(1)
            verdict = m.group(2).lower()
            reason = m.group(3).strip().rstrip(".!? ")[:MAX_TEXT_LEN]

            # Locate the target's most recent contribution before this tag.
            target_entries = by_author.get(target_name_raw.lower(), [])
            target = None
            try:
                tag_dt = _dt.datetime.fromisoformat(ts)
            except (TypeError, ValueError):
                tag_dt = None
            for cand in reversed(target_entries):  # entries are time-ordered
                cand_ts = cand.get("ts", "")
                if not cand_ts or cand_ts >= ts:
                    continue
                # Lookback window check
                if tag_dt is not None:
                    try:
                        cand_dt = _dt.datetime.fromisoformat(cand_ts)
                        if (tag_dt - cand_dt).total_seconds() > TAG_LOOKBACK_HOURS * 3600:
                            break
                    except ValueError:
                        pass
                target = cand
                break
            if target is None:
                log.info("supervisor tag has no resolvable target: @%s %s — (no prior contribution within %dh)",
                         target_name_raw, verdict, TAG_LOOKBACK_HOURS)
                continue

            tags.append({
                "tag_entry":     entry,
                "target_entry":  target,
                "target_name":   (target.get("from") or target_name_raw).strip(),
                "verdict":       verdict,
                "reason":        reason,
            })
    return tags


def write_supervisor_exemplars(tag: dict[str, Any]) -> int:
    """Write one exemplar file under <bot>/<good|bad>/by-supervisor/<id>.json."""
    target = tag["target_entry"]
    target_name = tag["target_name"]
    verdict = tag["verdict"]
    bot_id = (target.get("bot_id") or _safe_name(target_name)).strip() or _safe_name(target_name)
    bot_id = _safe_name(bot_id)

    # Stable id: hash of (target ts + tag ts + verdict). Re-running on the
    # same data produces the same file (idempotent).
    seed = (target.get("ts", "") + "|" + tag["tag_entry"].get("ts", "") + "|" + verdict).encode("utf-8")
    eid = hashlib.sha1(seed).hexdigest()[:12]

    record = {
        "source":             "supervisor",
        "weight":             2.0,
        "scored_at":          _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "verdict":            verdict,
        "supervisor_reason":  tag["reason"],
        "bot_name":           target_name,
        "bot_id":             bot_id,
        "supervisor": {
            "ts":   tag["tag_entry"].get("ts", ""),
            "from": tag["tag_entry"].get("from", ""),
            "text": (tag["tag_entry"].get("text") or "")[:MAX_TEXT_LEN],
        },
        "contribution": {
            "ts":   target.get("ts", ""),
            "text": (target.get("text") or "")[:MAX_TEXT_LEN],
        },
    }

    out_dir = EXEMPLARS_DIR / bot_id / verdict / "by-supervisor"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{eid}.json"
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1


# --- Main --------------------------------------------------------------------

def main() -> int:
    entries = _all_transcript_entries()
    if not entries:
        log.info("no transcript entries found under %s; nothing to do", COUNCIL_DIR)
        return 0

    # --- Stream 1: pin mining (the original) ---
    since_pin = _read_last_run()
    threads = find_threads(entries, since_ts=since_pin)
    pin_total = 0
    last_pin_ts = since_pin
    for t in threads:
        try:
            pin_total += write_exemplars(t)
            pin_ts = t["pin"].get("ts", "")
            if pin_ts > last_pin_ts:
                last_pin_ts = pin_ts
        except OSError as e:
            log.error("pin-write failed for thread starting %s: %s",
                      t["pin"].get("ts", ""), e)
    if last_pin_ts and last_pin_ts != since_pin:
        _write_last_run(last_pin_ts)

    # --- Stream 2: supervisor-tag mining ---
    since_tag = _read_last_tag_run()
    tags = find_supervisor_tags(entries, since_ts=since_tag)
    tag_total = 0
    last_tag_ts = since_tag
    for tag in tags:
        try:
            tag_total += write_supervisor_exemplars(tag)
            tag_ts = tag["tag_entry"].get("ts", "")
            if tag_ts > last_tag_ts:
                last_tag_ts = tag_ts
        except OSError as e:
            log.error("tag-write failed for target=%s: %s", tag.get("target_name", "?"), e)
    if last_tag_ts and last_tag_ts != since_tag:
        _write_last_tag_run(last_tag_ts)

    if not threads and not tags:
        log.info("no new pinned threads or supervisor tags since pins=%s tags=%s",
                 since_pin or "(forever)", since_tag or "(forever)")
        return 0

    log.info(
        "pins: %d thread(s) -> %d exemplar(s); supervisor: %d tag(s) -> %d exemplar(s); "
        "last_pin=%s last_tag=%s",
        len(threads), pin_total, len(tags), tag_total,
        last_pin_ts or "(none)", last_tag_ts or "(none)",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
