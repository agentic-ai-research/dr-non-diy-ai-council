"""
Reflection cron job — turns transcript pins into per-bot exemplar files.

This is the first implementation step from docs/learning-loops.md. It runs
unattended (cron / launchd, every ~5 min), reads the council transcript,
finds threads that closed since the last run, scores each justice's
contribution against the pin, and writes one JSON file per archived
contribution under ~/.council/exemplars/<bot_id>/<outcome>/<thread-id>.json.

Stdlib-only on purpose. No retraining, no embeddings, no vector store.
The library populated here is the input to step 3 (retrieval at compose
time, per-framework integration) — that's a separate piece of work.

Outcome scoring (v1, fuzzy on purpose; refine over time):
  - good   — bot's display name appears in the pin/ruling text.
  - bad    — pin/ruling explicitly overrules / rejects this bot.
  - mixed  — neither; the bot contributed but wasn't cited or ruled against.

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

COUNCIL_DIR    = Path(os.environ.get("COUNCIL_DIR", str(Path.home() / ".council")))
EXEMPLARS_DIR  = COUNCIL_DIR / "exemplars"
LAST_RUN_FILE  = EXEMPLARS_DIR / ".last-run"
SURROUNDING_N  = 5     # lines of context kept with each exemplar
MAX_TEXT_LEN   = 1500  # mirrors transcript schema

PIN_PREFIXES   = ("🪑 PIN:", "🪑 KILLED:", "🪑 REWORK:", "🪑 RULING:")
HUMAN_AUTHORS  = {"Dr Non", "system", ""}     # not scored

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


# --- Main --------------------------------------------------------------------

def main() -> int:
    since = _read_last_run()
    entries = _all_transcript_entries()
    if not entries:
        log.info("no transcript entries found under %s; nothing to do", COUNCIL_DIR)
        return 0

    threads = find_threads(entries, since_ts=since)
    if not threads:
        log.info("no new pinned threads since %s", since or "(forever)")
        return 0

    total = 0
    last_pin_ts = since
    for t in threads:
        try:
            total += write_exemplars(t)
            pin_ts = t["pin"].get("ts", "")
            if pin_ts > last_pin_ts:
                last_pin_ts = pin_ts
        except OSError as e:
            log.error("write failed for thread starting %s: %s",
                      t["pin"].get("ts", ""), e)

    if last_pin_ts and last_pin_ts != since:
        _write_last_run(last_pin_ts)

    log.info("scored %d thread(s), wrote %d exemplar file(s); last pin = %s",
             len(threads), total, last_pin_ts or "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
