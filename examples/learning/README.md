# Reflection cron — populates the per-bot exemplar library

The first implementation step from [docs/learning-loops.md](../../docs/learning-loops.md). The script runs **two parallel mining streams** on every cron tick:

| Stream | Source | Output path |
|---|---|---|
| **Pin mining** (original) | `🪑 PIN:` / `🪑 KILLED:` / `🪑 REWORK:` / `🪑 RULING:` lines | `~/.council/exemplars/<bot_id>/<good\|bad\|mixed>/<thread-id>.json` |
| **Supervisor tag mining** (added) | Dr Non's `@<bot> good\|bad — <reason>` tags | `~/.council/exemplars/<bot_id>/<good\|bad>/by-supervisor/<id>.json` |

The library it populates is the input for step 3 of [docs/learning-loops.md](../../docs/learning-loops.md) (retrieval at compose time) — that work happens elsewhere; the library can sit and grow before the consumers exist.

## What pin mining scores

- **good** — the bot's display name appears in the pin / ruling.
- **bad** — the pin / ruling explicitly overrules or rejects the bot.
- **mixed** — the bot contributed but isn't cited or ruled against.

The scoring is deliberately fuzzy in v1. Refine the heuristics in `_score()` over time.

## What supervisor tag mining captures

This is the supervised-training signal. When Dr Non writes a tag in any council message, the script:

1. Extracts each `@<bot> good|bad — <reason>` from the message.
2. Locates that bot's most recent prior contribution in the same thread (within ≤24h).
3. Writes a supervisor-flavored exemplar tagged `source: "supervisor"` and `weight: 2.0` (so retrieval ranks it above outcome-mined exemplars — Dr Non's explicit feedback is the strongest signal).

**Tag grammar:**

```
@bob good — clean sanity check, exactly what I needed
@hannah bad — wrong precedent, those weren't comparable
@otto good - sent the right draft, no edits needed
@radar bad -- two-source claim with weak corroboration
```

- The verdict is `good` or `bad` (case-insensitive). No `mixed` — supervisor tags are always opinionated; ambiguity is handled by *not* tagging.
- The separator is **em-dash (`—`)**, **two hyphens (`--`)**, or **single hyphen (`-`)**.
- Multiple tags in one message are all captured.
- Tags from anyone other than Dr Non are ignored — Peter, other bots, system actors all count as no-signal. Hardcoded by `from == "Dr Non"`.

**What gets written per tag:**

```json
{
  "source": "supervisor",
  "weight": 2.0,
  "verdict": "good",
  "supervisor_reason": "clean sanity check, exactly what I needed",
  "bot_name": "Bob",
  "bot_id": "bob",
  "supervisor": {
    "ts": "2026-05-03T10:01:00+00:00",
    "from": "Dr Non",
    "text": "@bob good — clean sanity check, exactly what I needed"
  },
  "contribution": {
    "ts": "2026-05-03T10:00:30+00:00",
    "text": "SANITY: clean. Q3 plan looks fine."
  }
}
```

**Idempotency:** the exemplar's filename hashes (target ts + tag ts + verdict). Re-running the cron on the same data overwrites the same file with identical content. Safe to run as often as you like.

**Lookback window:** if Dr Non tags `@bob good — …` but Bob hasn't posted in the last 24 hours, the tag is logged-and-skipped (no resolvable target). Adjust `TAG_LOOKBACK_HOURS` in `reflect.py` if you find this too tight or loose.

**Marker file:** `~/.council/exemplars/.last-tag-run` (separate from `.last-run` for pin mining, so the two streams don't interfere).

## Setup

1. Drop `reflect.py` somewhere on the council Mac (e.g., `~/.council/lib/reflect.py`).
2. Add a launchd plist (preferred over crontab on macOS — survives reboots, integrates with logs):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>ai.council.reflect</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/YOU/.council/lib/reflect.py</string>
  </array>
  <key>StartInterval</key>    <integer>300</integer>   <!-- 5 minutes -->
  <key>StandardErrorPath</key><string>/Users/YOU/.council/reflect.log</string>
  <key>RunAtLoad</key>        <true/>
</dict>
</plist>
```

Save as `~/Library/LaunchAgents/ai.council.reflect.plist`, then `launchctl load -w ~/Library/LaunchAgents/ai.council.reflect.plist`.

3. Or, simplest path — a crontab entry every 5 minutes:

```
*/5 * * * * /usr/bin/python3 /Users/YOU/.council/lib/reflect.py >> /Users/YOU/.council/reflect.log 2>&1
```

## Dry run

```
COUNCIL_DIR=/tmp/test-council python3 reflect.py
```

If you want to test against the real transcript without writing exemplars, just point `COUNCIL_DIR` at a temp directory after copying the transcript files in.

## Output layout

```
~/.council/exemplars/
├── .last-run                              # ISO timestamp of last processed pin
├── tenet/
│   ├── good/<thread-id>.json
│   ├── bad/<thread-id>.json
│   └── mixed/<thread-id>.json
├── eve/...
└── ...
```

Each `<thread-id>.json` is small (≤ 4KB), text JSON, idempotent — re-running the script overwrites the same file with the same content. To forget an exemplar (e.g., a bad pin polluted the library), `rm` the file. The next run won't recreate it because `.last-run` has already advanced past that pin.
