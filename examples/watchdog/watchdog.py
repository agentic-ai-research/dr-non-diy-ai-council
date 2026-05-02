"""
watchdog.py — disciplined health-check + restart loop for a council bot.

The April 28 failure mode this prevents:
  Watchdog spammed "Gateway DOWN — restart failed" every 5 minutes for 30
  hours. Dr Non never noticed because identical alerts in the council
  channel are noise. The harness kept trying restarts on a binary that
  was 401-ing on every attempt — wasted CPU, wasted log space, and the
  room had no idea it was operating without Otto.

The contract this enforces (see docs/resilience.md, Layer 2):
  1. Restart up to N=5 times with exponential backoff.
  2. After N failures, STOP. The binary is broken; a sixth attempt won't
     fix it. Dr Non's hands are needed.
  3. DM Dr Non once with [GATEWAY-DOWN] + a 200-line tail of the error log.
  4. Heartbeat every HEARTBEAT_HOURS (default 6) while still down. One
     line. Same chat as the original DM.
  5. On recovery, one final DM, then silence.
  6. NEVER post identical alerts to the council group. Council is for
     working bots; the DM is for broken ones.

Stdlib + Telegram Bot API only. Drop into ~/.council/lib/ and wrap in a
launchd plist that runs every 60 s.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import shutil
import socket
import subprocess  # only used to drive `launchctl` with literal arguments — see Lock 5 note below
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# --- Config ------------------------------------------------------------------

LABEL              = os.environ["WATCHDOG_LABEL"]              # e.g. "ai.openclaw.gateway"
ERR_LOG_PATH       = Path(os.environ["WATCHDOG_ERR_LOG"])      # path to the bot's stderr log
TG_BOT_TOKEN       = os.environ["WATCHDOG_TG_BOT_TOKEN"]       # the watchdog's own bot token
TG_DM_CHAT_ID      = os.environ["WATCHDOG_TG_DM_CHAT_ID"]      # Dr Non's user id (DM chat)
STATE_FILE         = Path(os.environ.get("WATCHDOG_STATE",
                                         str(Path.home() / ".council" / "watchdog" / f"{LABEL}.state.json")))

MAX_ATTEMPTS       = int(os.environ.get("WATCHDOG_MAX_ATTEMPTS", "5"))
BACKOFF_SECONDS    = [30, 60, 120, 240, 480]   # exponential, indexed by attempt-1
HEARTBEAT_HOURS    = float(os.environ.get("WATCHDOG_HEARTBEAT_HOURS", "6"))
LOG_TAIL_LINES     = int(os.environ.get("WATCHDOG_LOG_TAIL_LINES", "200"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog %(label)s] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.LoggerAdapter(logging.getLogger("watchdog"), {"label": LABEL})


# --- State -------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"attempts": 0, "stopped": False, "down_since": None,
            "last_attempt_ts": None, "last_heartbeat_ts": None}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# --- launchctl interface -----------------------------------------------------

def _is_running() -> bool:
    """True iff `launchctl list <LABEL>` reports a running PID > 0."""
    try:
        out = subprocess.run(
            ["launchctl", "list", LABEL],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    # First line is "<pid> <last-exit> <label>"; pid '-' means not running.
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("{"):
            continue
        parts = line.split(None, 2)
        if len(parts) >= 1 and parts[0] not in ("-", "PID"):
            try:
                return int(parts[0]) > 0
            except ValueError:
                pass
    return False


def _attempt_restart() -> None:
    """Bootstrap-out then bootstrap-in via launchctl. Best-effort; never raises."""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    for cmd in [
        ["launchctl", "bootout",    domain, str(plist)],
        ["launchctl", "bootstrap", domain, str(plist)],
    ]:
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("launchctl %s failed: %s", cmd[1], e)


def _tail_err_log() -> str:
    if not ERR_LOG_PATH.exists():
        return "(no error log)"
    try:
        with ERR_LOG_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = min(size, 64 * 1024)
            f.seek(size - block)
            data = f.read(block).decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-LOG_TAIL_LINES:])
    except OSError:
        return "(error log unreadable)"


# --- Telegram DM (Bot API, plain HTTP, stdlib only) --------------------------

def _dm(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": TG_DM_CHAT_ID,
        "text":    text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log.error("DM failed: %s", e)
        return False


# --- Main loop (one tick per launchd run) ------------------------------------

def main() -> int:
    state = _load_state()
    now = _dt.datetime.now(_dt.timezone.utc)

    if _is_running():
        if state["attempts"] > 0 or state["stopped"]:
            # Recovery!
            down_since = state.get("down_since") or now.isoformat()
            try:
                delta = now - _dt.datetime.fromisoformat(down_since)
                pretty = f"{int(delta.total_seconds() // 3600)}h {int((delta.total_seconds() % 3600) // 60)}m"
            except (TypeError, ValueError):
                pretty = "unknown"
            _dm(f"[{LABEL}] Recovered. Down for {pretty}.")
            log.info("recovered after %s; clearing state", pretty)
        _save_state({"attempts": 0, "stopped": False, "down_since": None,
                     "last_attempt_ts": None, "last_heartbeat_ts": None})
        return 0

    # Not running. Either we should restart, or we already gave up.
    if state["stopped"]:
        # Heartbeat cadence — do not retry, just remind.
        last_hb = state.get("last_heartbeat_ts")
        send_heartbeat = (
            last_hb is None or
            (now - _dt.datetime.fromisoformat(last_hb)).total_seconds() >= HEARTBEAT_HOURS * 3600
        )
        if send_heartbeat:
            down_since = state.get("down_since") or now.isoformat()
            try:
                delta = now - _dt.datetime.fromisoformat(down_since)
                pretty = f"{int(delta.total_seconds() // 3600)}h"
            except (TypeError, ValueError):
                pretty = "unknown duration"
            _dm(f"[{LABEL}] Still down. {pretty} since first failure.")
            state["last_heartbeat_ts"] = now.isoformat()
            _save_state(state)
        return 0

    # Still trying. Apply backoff before each attempt.
    attempts = state.get("attempts", 0)
    last_attempt_ts: Optional[str] = state.get("last_attempt_ts")
    if attempts > 0 and last_attempt_ts:
        try:
            since_last = (now - _dt.datetime.fromisoformat(last_attempt_ts)).total_seconds()
        except ValueError:
            since_last = float("inf")
        backoff = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        if since_last < backoff:
            log.info("in backoff window (%.0fs of %ds), skipping", since_last, backoff)
            return 0

    if state.get("down_since") is None:
        state["down_since"] = now.isoformat()

    attempts += 1
    log.info("restart attempt %d/%d", attempts, MAX_ATTEMPTS)
    _attempt_restart()
    state["attempts"] = attempts
    state["last_attempt_ts"] = now.isoformat()

    # Give it a moment, then check.
    time.sleep(5)
    if _is_running():
        log.info("attempt %d succeeded", attempts)
        # Will be cleared on the next tick when _is_running stays True.
        _save_state(state)
        return 0

    if attempts >= MAX_ATTEMPTS:
        # Stop trying. DM Dr Non once with the smoking gun.
        tail = _tail_err_log()
        first_line = tail.splitlines()[-1] if tail else "(no log)"
        msg = (
            f"[{LABEL}] {MAX_ATTEMPTS} restart attempts failed.\n"
            f"Last log line: {first_line[:300]}\n"
            f"\n--- log tail ({LOG_TAIL_LINES} lines) ---\n"
            f"{tail[-3500:]}"  # Telegram message cap is 4096
        )
        _dm(msg)
        log.error("giving up after %d attempts; DM'd Dr Non", MAX_ATTEMPTS)
        state["stopped"] = True
        state["last_heartbeat_ts"] = now.isoformat()

    _save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
