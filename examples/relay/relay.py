"""
Council relay bridge — uses a Telegram user-account client (Telethon) to
re-post bot messages so other bots can see them.

Why this exists:
  Telegram's bot API does not deliver bot messages to other bots. The shared
  transcript file in transcript-fix.md solves that for frameworks we can
  patch (nanobot, Hermes, eve-coder). This relay solves it for frameworks
  we cannot patch (OpenClaw / PicoClaw Go binaries) by re-posting their
  messages from a user account, whose messages ARE delivered to bots.

Companion to:
  docs/relay-bridge.md — the design doc.
  docs/transcript-fix.md — the file-based fix this complements.

Usage:
  python relay.py /path/to/config.json

Dependencies:
  pip install telethon

Reads:   config JSON (see config.example.json), council group ID, bot list.
Writes:  ~/.council/transcript.jsonl (same source of truth as transcript-fix).
         Re-post into the council group with a "[council-relay]" tag.
"""

import asyncio
import json
import logging
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events

# --- Config ------------------------------------------------------------------

if len(sys.argv) != 2:
    print("usage: relay.py /path/to/config.json", file=sys.stderr)
    sys.exit(2)

CONFIG = json.loads(Path(sys.argv[1]).read_text())

SESSION_NAME      = CONFIG["session_name"]
API_ID            = int(CONFIG["api_id"])
API_HASH          = CONFIG["api_hash"]
COUNCIL_GROUP_ID  = int(CONFIG["council_group_id"])
BOT_USERNAMES     = set(CONFIG["bot_usernames"])         # {"NonTenet_bot", ...}
BOT_NAMES         = CONFIG.get("bot_names", {})          # {"NonTenet_bot": "Tenet", ...}
RELAY_TAG         = "[council-relay]"
TRANSCRIPT_PATH   = Path.home() / ".council" / "transcript.jsonl"
MACHINE           = socket.gethostname()

# --- Secret redaction (matches Lock 2 in inter-bot-protocols.md) -------------

REDACT_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"),                "sk-…REDACTED"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"),               "ghp_…REDACTED"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),       "xox?-…REDACTED"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),      "Bearer …REDACTED"),
    (re.compile(r"AKIA[0-9A-Z]{16}"),                   "AKIA…REDACTED"),
    (re.compile(r"(?i)password\s*[:=]\s*\S+"),          "password=REDACTED"),
]

def redact(text: str) -> str:
    for pat, repl in REDACT_PATTERNS:
        text = pat.sub(repl, text)
    return text

# --- Logging -----------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [relay] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("relay")

# --- Transcript append (same schema as transcript-fix.md) --------------------

def append_transcript(name: str, bot_id: str, text: str) -> bool:
    line = json.dumps(
        {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "from":    name,
            "bot_id":  bot_id,
            "machine": MACHINE,
            "text":    redact(text),
        },
        ensure_ascii=False,
    )
    try:
        TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRANSCRIPT_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except OSError as e:
        log.error("transcript append failed: %s", e)
        return False

# --- Client and handlers -----------------------------------------------------

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
ME_ID: int | None = None  # set at startup

@client.on(events.NewMessage(chats=COUNCIL_GROUP_ID))
async def on_message(event):
    sender = await event.get_sender()
    if sender is None:
        return

    # Anti-loop guard #1 — never relay our own messages.
    if ME_ID is not None and sender.id == ME_ID:
        return

    username = getattr(sender, "username", None)
    if not username:
        return  # not a bot, not a tagged user — ignore

    # Only relay messages from registered council bots.
    if username not in BOT_USERNAMES:
        return

    text = (event.message.message or "").strip()
    if not text:
        return  # nothing to relay (sticker, photo without caption, etc.)

    # Anti-loop guard #2 — if a tagged relay message somehow comes through
    # (e.g., another relay instance, or someone manually re-posting),
    # do not relay it again.
    if text.startswith(RELAY_TAG):
        return

    bot_id = username
    name   = BOT_NAMES.get(username, username)

    # Step 1: append to the shared transcript (source of truth).
    # Fail-closed: if append fails, do not re-post either.
    if not append_transcript(name, bot_id, text):
        log.error("skipping re-post because transcript append failed")
        return

    # Step 2: re-post so unpatched bots receive the message in their queue.
    repost = f"{RELAY_TAG} [{name}]: {redact(text)}"
    try:
        await client.send_message(COUNCIL_GROUP_ID, repost)
        log.info("relayed %s (%d chars)", name, len(text))
    except Exception as e:
        log.error("re-post failed for %s: %s", name, e)

# --- Main --------------------------------------------------------------------

async def main():
    global ME_ID
    await client.start()
    me = await client.get_me()
    ME_ID = me.id
    log.info(
        "connected as @%s (id=%d), monitoring group %d, %d bots registered",
        me.username, me.id, COUNCIL_GROUP_ID, len(BOT_USERNAMES),
    )
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("shutting down on Ctrl-C")
