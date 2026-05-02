# Reflection cron — populates the per-bot exemplar library

The first implementation step from [docs/learning-loops.md](../../docs/learning-loops.md). This script reads the council transcript, finds pinned threads since its last run, scores each justice's contribution against the pin text, and writes one JSON file per archived contribution to `~/.council/exemplars/<bot_id>/<outcome>/<thread-id>.json`.

The library it populates is the input for step 3 (retrieval at compose time, per-framework integration) — that work happens elsewhere; the library can sit and grow before the consumers exist.

## What it scores

- **good** — the bot's display name appears in the pin / ruling.
- **bad** — the pin / ruling explicitly overrules or rejects the bot.
- **mixed** — the bot contributed but isn't cited or ruled against.

The scoring is deliberately fuzzy in v1. Refine the heuristics in `_score()` over time.

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
