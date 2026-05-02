"""
hourly-digest.py — noN's silent-observer cron job.

Reads ~/.council/transcript.jsonl for the last hour and writes a
markdown digest to:
    $VAULT_DIR/council/analytics/YYYY-MM-DD/HH.md

This is the council's canonical hourly analytics record, kept in
Dr Non's Obsidian vault. See:
- docs/justice-roles.md — noN's extended role (silent archivist).
- docs/multi-task.md — the standing-order pattern this fits.
- docs/learning-loops.md — the weekly drift detector reads these.

Stdlib-only. Idempotent (rewriting an existing hour's file is fine).
Cron entry every hour, on the hour:

    0 * * * * VAULT_DIR=/Users/YOU/Vault /usr/bin/python3 /path/to/hourly-digest.py \\
              >> /Users/YOU/.council/digest.log 2>&1
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --- Config ------------------------------------------------------------------

COUNCIL_DIR = Path(os.environ.get("COUNCIL_DIR", str(Path.home() / ".council")))
VAULT_DIR   = Path(os.environ.get("VAULT_DIR",   str(Path.home() / "Vault")))

PIN_PREFIXES  = ("🪑 PIN:", "🪑 KILLED:", "🪑 REWORK:", "🪑 RULING:")
BENCH_PREFIX  = "BENCH:"
HUMAN_AUTHORS = {"Dr Non", "system", ""}
THREAD_RE     = re.compile(r"^\[#([a-z0-9_-]+)\]\s*")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [hourly-digest] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("hourly-digest")

# --- Helpers -----------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _entries_around(now: _dt.datetime) -> list[dict]:
    """Pull both today's and yesterday's transcript files (handles the
    midnight rollover when the digest runs for 23:00 UTC)."""
    entries: list[dict] = []
    for d in ((now - _dt.timedelta(days=1)).date(), now.date()):
        f = COUNCIL_DIR / f"transcript-{d.isoformat()}.jsonl"
        entries.extend(_read_jsonl(f))
    return entries


def _within_window(entry: dict, start_iso: str, end_iso: str) -> bool:
    ts = entry.get("ts", "")
    return start_iso <= ts < end_iso


def _thread_of(text: str) -> str:
    m = THREAD_RE.match(text or "")
    return m.group(1) if m else "untagged"


def _strip_thread_prefix(text: str) -> str:
    return THREAD_RE.sub("", text or "", count=1).strip()


# --- Main --------------------------------------------------------------------

def main() -> int:
    now = _dt.datetime.now(_dt.timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - _dt.timedelta(hours=1)
    start_iso = start.isoformat(timespec="seconds")
    end_iso   = end.isoformat(timespec="seconds")

    all_entries = _entries_around(now)
    recent = [e for e in all_entries if _within_window(e, start_iso, end_iso)]

    if not recent:
        log.info("no entries in window %s..%s; skipping write", start_iso, end_iso)
        return 0

    # Aggregate
    by_justice: Counter[str]               = Counter()
    by_thread:  defaultdict[str, list[dict]] = defaultdict(list)
    pins:    list[dict] = []
    benches: list[dict] = []

    for e in recent:
        author = (e.get("from") or "").strip()
        text   = e.get("text") or ""
        thread = _thread_of(text)
        body   = _strip_thread_prefix(text)

        by_justice[author] += 1
        by_thread[thread].append(e)

        if body.startswith(PIN_PREFIXES):
            pins.append({"thread": thread, "from": author, "text": body[:240]})
        if body.startswith(BENCH_PREFIX):
            benches.append({"thread": thread, "from": author, "text": body[:240]})

    # Compose
    hour_label = end.strftime("%H")
    date_label = end.strftime("%Y-%m-%d")
    out_dir = VAULT_DIR / "council" / "analytics" / date_label
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as ex:
        log.error("could not create %s: %s", out_dir, ex)
        return 0  # cron-friendly: never crash on disk issues
    out_path = out_dir / f"{hour_label}.md"

    front_matter = (
        "---\n"
        f"date: {date_label}\n"
        f"hour: {hour_label}\n"
        f"window_start: {start_iso}\n"
        f"window_end:   {end_iso}\n"
        f"messages:     {len(recent)}\n"
        f"threads:      {len(by_thread)}\n"
        f"pins:         {len(pins)}\n"
        f"benches:      {len(benches)}\n"
        f"author: noN\n"
        "tags: [council, analytics, hourly]\n"
        "---\n"
    )

    parts: list[str] = [front_matter, ""]
    parts.append(f"# Council — {date_label} {hour_label}:00 UTC")
    parts.append("")
    parts.append(
        f"*Silent observer log. {len(recent)} messages across "
        f"{len(by_thread)} thread(s). {len(pins)} pin(s), {len(benches)} bench(es).*"
    )
    parts.append("")

    if pins:
        parts.append("## Pins")
        for p in pins:
            parts.append(f"- `[#{p['thread']}]` **{p['from']}** — {p['text']}")
        parts.append("")

    if benches:
        parts.append("## Benches awaiting Dr Non")
        for b in benches:
            parts.append(f"- `[#{b['thread']}]` **{b['from']}** — {b['text']}")
        parts.append("")

    parts.append("## Activity by justice")
    for name, count in by_justice.most_common():
        if name in HUMAN_AUTHORS:
            continue
        parts.append(f"- {name}: {count}")
    parts.append("")

    parts.append("## Activity by thread")
    for thread, entries in sorted(by_thread.items(), key=lambda kv: -len(kv[1])):
        parts.append(f"- `#{thread}` — {len(entries)} message(s)")
    parts.append("")

    # Optional narrative slot — left blank for v1; an LLM call can fill
    # this on hosts that have one available without breaking the cron's
    # stdlib-only contract.
    parts.append("## noN's note")
    parts.append("")
    parts.append("*(blank — structured stats above are the truth-of-record. "
                 "Optional model call may fill this section in a later version.)*")
    parts.append("")

    try:
        out_path.write_text("\n".join(parts), encoding="utf-8")
    except OSError as ex:
        log.error("write failed: %s", ex)
        return 0
    log.info("wrote %s (%d msgs)", out_path, len(recent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
