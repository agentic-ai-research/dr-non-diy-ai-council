"""
Reference implementation of the council shared-transcript helper.

This is the file that lives at ~/.council/lib/transcript.py in a deployed
council. Each bot framework imports this and calls .append() / .read_recent()
to coordinate without needing Telegram bot-to-bot delivery (which doesn't
exist).

See docs/transcript-fix.md for the architectural rationale.

Stdlib-only on purpose — drop into any Python bot without dependency drift.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

COUNCIL_DIR = Path(os.environ.get("COUNCIL_DIR", str(Path.home() / ".council")))
COUNCIL_CHAT_ID = os.environ.get("COUNCIL_CHAT_ID", "REPLACE_WITH_YOUR_GROUP_CHAT_ID")
SYMLINK = COUNCIL_DIR / "transcript.jsonl"

DEFAULT_RECENT_N = 25
MAX_TEXT_LEN = 1500


def _today_path() -> Path:
    return COUNCIL_DIR / f"transcript-{_dt.date.today().isoformat()}.jsonl"


def _ensure_symlink() -> Path:
    COUNCIL_DIR.mkdir(parents=True, exist_ok=True)
    target = _today_path()
    target.touch(exist_ok=True)
    try:
        if SYMLINK.is_symlink():
            if SYMLINK.resolve() != target.resolve():
                SYMLINK.unlink()
                SYMLINK.symlink_to(target.name)
        elif not SYMLINK.exists():
            SYMLINK.symlink_to(target.name)
    except OSError:
        pass
    return target


def bot_name() -> str:
    """This bot's council display name. Set $COUNCIL_BOT_NAME in the launchd plist."""
    return os.environ.get("COUNCIL_BOT_NAME", "Unknown").strip() or "Unknown"


def append(text: str, *, from_name: Optional[str] = None) -> None:
    """Append an outbound council message. Failures are non-fatal."""
    if not text or not text.strip():
        return
    try:
        target = _ensure_symlink()
        record = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "from": from_name or bot_name(),
            "text": text[:MAX_TEXT_LEN],
        }
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[council.transcript] append failed: {e}", file=sys.stderr)


def read_recent(n: int = DEFAULT_RECENT_N) -> List[dict]:
    target = _today_path()
    if not target.exists():
        return []
    try:
        lines = target.read_text(encoding="utf-8").strip().splitlines()
        out: List[dict] = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except Exception as e:
        print(f"[council.transcript] read failed: {e}", file=sys.stderr)
        return []


def build_recent_block(n: int = DEFAULT_RECENT_N, *, exclude_self: bool = False) -> str:
    """Render recent transcript entries as a system-prompt block. Empty if no entries."""
    me = bot_name()
    entries = read_recent(n)
    if exclude_self:
        entries = [e for e in entries if e.get("from") != me]
    if not entries:
        return ""

    lines = ["## COUNCIL TRANSCRIPT (recent — what the council has already said)", ""]
    for e in entries:
        ts_full = e.get("ts", "")
        ts_short = ts_full.split("T")[-1].split("+")[0].split(".")[0] if "T" in ts_full else ts_full
        from_name = e.get("from", "?")
        text = (e.get("text", "") or "").strip().replace("\n", " ")
        if len(text) > 400:
            text = text[:400] + "…"
        lines.append(f"[{ts_short} {from_name}] {text}")

    lines.append("")
    lines.append(
        "Read this BEFORE composing your reply. Build on or disagree with these "
        "contributions explicitly. If your point has already been made by another "
        "justice, stay silent — silence is a valid council move."
    )
    return "\n".join(lines)


def is_council_chat(chat_id) -> bool:
    return str(chat_id) == COUNCIL_CHAT_ID
