# Hourly digest — noN's silent-observer cron

The council's canonical hourly analytics record, kept in Dr Non's Obsidian vault. noN's primary mode is silent observation; this script is how the silence becomes a written record. See [docs/justice-roles.md](../../docs/justice-roles.md) for the role spec and [docs/multi-task.md](../../docs/multi-task.md) for the standing-order pattern this fits.

## What it does

Each hour, on the hour:

1. Reads `~/.council/transcript-YYYY-MM-DD.jsonl` (and yesterday's, to handle the 23:00 UTC rollover).
2. Filters to entries within the last 60 minutes.
3. Aggregates by justice and by thread; lists pins and benches.
4. Writes one markdown file to `$VAULT_DIR/council/analytics/YYYY-MM-DD/HH.md` — Obsidian-friendly, front-matter + headings.

The file is the canonical hourly council record. Weekly drift detection ([docs/learning-loops.md](../../docs/learning-loops.md)) and any of Dr Non's own queries can read it without touching the raw transcript.

## Setup

1. Drop `hourly-digest.py` somewhere on the council Mac (e.g., `~/.council/lib/hourly-digest.py`).
2. Set `VAULT_DIR` to your Obsidian vault root.
3. **Launchd plist (preferred on macOS):**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>ai.council.hourly-digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/YOU/.council/lib/hourly-digest.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Minute</key><integer>0</integer></dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>VAULT_DIR</key>    <string>/Users/YOU/Vault</string>
    <key>COUNCIL_DIR</key>  <string>/Users/YOU/.council</string>
  </dict>
  <key>StandardErrorPath</key><string>/Users/YOU/.council/digest.log</string>
  <key>RunAtLoad</key>        <true/>
</dict>
</plist>
```

Save as `~/Library/LaunchAgents/ai.council.hourly-digest.plist`, then `launchctl load -w ~/Library/LaunchAgents/ai.council.hourly-digest.plist`.

4. **Or, simplest path — crontab:**

```
0 * * * * VAULT_DIR=/Users/YOU/Vault /usr/bin/python3 /path/to/hourly-digest.py >> /Users/YOU/.council/digest.log 2>&1
```

## Dry run

```
COUNCIL_DIR=/tmp/test-council VAULT_DIR=/tmp/test-vault python3 hourly-digest.py
```

Exits 0 with no transcript present. Exits 0 if `$VAULT_DIR` is unwritable (cron-friendly — never crash a scheduled job on disk issues).

## Output shape

`$VAULT_DIR/council/analytics/2026-05-02/14.md`:

```markdown
---
date: 2026-05-02
hour: 14
window_start: 2026-05-02T14:00:00+00:00
window_end:   2026-05-02T15:00:00+00:00
messages:     23
threads:      3
pins:         2
benches:      1
author: noN
tags: [council, analytics, hourly]
---

# Council — 2026-05-02 14:00 UTC

*Silent observer log. 23 messages across 3 thread(s). 2 pin(s), 1 bench(es).*

## Pins
- `[#bangkok-contract]` **Tenet** — 🪑 PIN: take it with 90d escape clause.
- `[#deepwork-auth]` **Tenet** — 🪑 PIN: shipped.

## Benches awaiting Dr Non
- `[#x-monitor]` **Otto** — BENCH: draft reply to @user123 (public, neutral-positive)…

## Activity by justice
- Tenet: 6
- Hannah: 4
- Otto: 4
- Eve: 3
- Ada: 2
- Civic: 1
- Aviva: 1

## Activity by thread
- `#deepwork-auth` — 9 message(s)
- `#bangkok-contract` — 8 message(s)
- `#x-monitor` — 6 message(s)

## noN's note

*(blank — structured stats above are the truth-of-record. Optional model call may fill this section in a later version.)*
```

## What it does NOT do

- **No LLM call.** v1 is structured stats only — fast, cheap, deterministic. The narrative slot exists for a future model-augmented pass; the analytics work without it.
- **No council post.** noN remains silent in the group. Her once-per-session interrupt rule is unchanged ([docs/justice-roles.md](../../docs/justice-roles.md)).
- **No edits to older digests.** Each hour's file is idempotent; re-running rewrites it identically.
- **No transcript modification.** Read-only on `~/.council/transcript-*.jsonl`.
