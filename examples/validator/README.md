# Validator — make council protocol drift visible

A cron-driven post-write validator for `~/.council/transcript.jsonl`. Reads new entries every 30s, checks each against the protocol (palette discipline, identity fields, lane refusals, token-shape leaks), and logs violations. **Surfaces drift; doesn't block.** A bot can still post a malformed line; the validator catches it within 30 seconds and names exactly what's wrong, so the room can self-correct.

The point: today's protocol is markdown. The validator is the bridge between *policy* and *code* — the cheapest possible enforcement, before the heavier per-framework loaders ([ROADMAP.md](../../ROADMAP.md) M1) land.

## What it checks (all from the protocol stack)

| Check | Source rule |
|---|---|
| **Required fields**: `ts`, `from`, `text` on every line | [communication-protocol.md](../../docs/communication-protocol.md) |
| **Recommended fields**: `bot_id`, `machine` | [inter-bot-protocols.md §4](../../docs/inter-bot-protocols.md) |
| **Palette discipline**: each justice opens with a verb from her palette | [production-mode.md](../../docs/production-mode.md), [justice-roles.md](../../docs/justice-roles.md) |
| **Lane refusals**: thinkers (Tenet, Hannah, Ada, Ana, Civic, Aviva, Bob, noN) must not emit tool-call verbs | [inter-bot-protocols.md §1](../../docs/inter-bot-protocols.md) capability matrix |
| **Token-shape leaks**: `bot<digits>:`, `sk-`, `ghp_`, `AKIA…` etc. in transcript text | Lock 2, [SECURITY.md](../../SECURITY.md) |

## Setup

```bash
mkdir -p ~/.council/lib
cp examples/validator/validator.py ~/.council/lib/
```

### launchd (preferred on macOS — every 30s)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>ai.council.validator</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/YOU/.council/lib/validator.py</string>
  </array>
  <key>StartInterval</key>    <integer>30</integer>
  <key>StandardErrorPath</key><string>/Users/YOU/.council/validator.log</string>
  <key>StandardOutPath</key>  <string>/Users/YOU/.council/validator.log</string>
  <key>RunAtLoad</key>        <true/>
</dict>
</plist>
```

Save as `~/Library/LaunchAgents/ai.council.validator.plist`, then `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.council.validator.plist`.

### crontab fallback

```
* * * * *    /usr/bin/python3 /Users/YOU/.council/lib/validator.py
* * * * *    sleep 30 && /usr/bin/python3 /Users/YOU/.council/lib/validator.py
```

## What you get in the log

For each violation found, a line like:

```
2026-05-02 23:48:00 [validator] WARNING VIOLATION  ts=2026-05-02T23:47:51+07:00  from=Hannah  count=1
2026-05-02 23:48:00 [validator] WARNING            lane violation: Hannah (thinker) used tool verb 'PRE-CALL:'
```

Or:

```
2026-05-02 23:48:00 [validator] WARNING VIOLATION  ts=2026-05-02T23:47:55+07:00  from=Otto    count=1
2026-05-02 23:48:00 [validator] WARNING            off-palette: Otto should open with one of ['BENCH:', 'BLOCKED-EXTERNAL:', 'BLOCKER:', 'CHECKPOINT:', 'DRAFT:']… but said 'I think we should consider sending this email…'
```

## What the validator does NOT do

- **Doesn't block bots from posting.** Today's drift surface is the transcript file; the validator reads after the fact. To gate at write time, the per-framework loaders ([ROADMAP.md](../../ROADMAP.md) M1) are the right tool.
- **Doesn't post `🪑 RULING:` to council on every violation.** That would create more drift. Surfacing in `validator.log` plus aggregated counts in `validator.state.json` is the read-only signal; you can plug a Telegram DM bridge in if you want stronger feedback.
- **Doesn't enforce identity routing.** That's a separate concern handled by [examples/identity/](../identity/). The validator catches a *symptom* (a bot using off-palette verbs because its SOUL is wrong) but not the cause.
- **Doesn't redact existing token leaks.** It detects them so you know to act; the redaction filter at [examples/security/redact-tokens.py](../security/redact-tokens.py) is the prevention.

## Tuning

The palettes baked into `validator.py` are the canonical ones from the protocol stack as of 2026-05-02. To extend (e.g., when Nun ships, or when a new justice joins), edit `PALETTES` at the top of the file. Keep that table consistent with [`docs/production-mode.md`](../../docs/production-mode.md) and [`docs/justice-roles.md`](../../docs/justice-roles.md).

## Verification

```bash
COUNCIL_DIR=/tmp/test-council python3 examples/validator/validator.py
# Expected: "no transcripts ... nothing to do"; exit 0.

# Or against your real transcript (read-only, safe):
python3 examples/validator/validator.py
# Expected: "validated N new entries; M violations across K bots".
```

The first run after install will validate every line in your existing transcripts (slow). Subsequent runs only check entries with `ts > last seen`, so the steady-state cost is constant per cron tick.
