# Watchdog — Layer-2 of the resilience stack

Drop-in disciplined health-check + restart loop for any council bot. See [docs/resilience.md](../../docs/resilience.md) for the full three-layer story; this directory is the reference implementation of Layer 2 (watchdog discipline).

## What it does

For one launchd-managed bot service (one `Label`, e.g. `ai.openclaw.gateway`):

1. Each tick (run every 60 s by launchd), checks if the bot's `launchctl list <Label>` is reporting a running PID.
2. If down: tries to restart, with **exponential backoff** between attempts — `30s · 60s · 120s · 240s · 480s`.
3. After **5 attempts**, gives up. The binary is broken; a sixth attempt won't fix it.
4. **DMs Dr Non** with `[<Label>] 5 restart attempts failed.` plus the last log line and a 200-line tail of the bot's stderr log. **Never** posts to the council group.
5. **Heartbeat every 6 hours** while still down — one DM, one line, same chat. *"Still down. 23h since first failure."*
6. **On recovery**, one final DM (*"Recovered. Down for 23h 45m."*), then silence and full state reset.

## What it explicitly does NOT do

- **Does not post to the council group.** Council is for working bots; the DM is for broken ones. (This is the rule the April 28 watchdog violated for 30 hours.)
- **Does not retry past 5 attempts.** If the binary keeps 401-ing, your hands are needed; the watchdog stays out of the way.
- **Does not exec content sourced from any message.** The script's only `subprocess` calls drive `launchctl` with literal arguments; there is no path from a council message to a shell command.
- **Does not own credentials.** The watchdog's own bot token (a separate Telegram bot whose only job is DMing Dr Non) is the only secret it touches. Per Lock 3 — its own keychain item.

## Setup

### 1. Create a Telegram bot whose only job is alerting you.

Talk to [@BotFather](https://t.me/BotFather), `/newbot`, name it whatever (`council-watchdog-bot`), grab the token. This bot is **separate** from any council bot — keep its blast radius small. DM it once from your account to register your `chat_id`; you can find your `chat_id` by visiting `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending the DM.

### 2. Drop `watchdog.py` somewhere on the council Mac.

```
~/.council/lib/watchdog.py
```

### 3. Wrap it in a launchd plist.

One plist per bot you want watched. Example for OpenClaw:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>ai.council.watchdog.openclaw</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/YOU/.council/lib/watchdog.py</string>
  </array>
  <key>StartInterval</key>    <integer>60</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>WATCHDOG_LABEL</key>           <string>ai.openclaw.gateway</string>
    <key>WATCHDOG_ERR_LOG</key>         <string>/Users/YOU/.openclaw/logs/gateway.err.log</string>
    <key>WATCHDOG_TG_BOT_TOKEN</key>    <string>REPLACE_WITH_BOTFATHER_TOKEN</string>
    <key>WATCHDOG_TG_DM_CHAT_ID</key>   <string>REPLACE_WITH_YOUR_CHAT_ID</string>
  </dict>
  <key>StandardErrorPath</key><string>/Users/YOU/.council/watchdog/openclaw.log</string>
  <key>RunAtLoad</key>        <true/>
</dict>
</plist>
```

Save as `~/Library/LaunchAgents/ai.council.watchdog.openclaw.plist`, then:

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.council.watchdog.openclaw.plist
```

### 4. Run one watchdog per bot service.

You can have a fleet of these — one for OpenClaw, one for Hermes, one for nanobot. Each one has its own `LABEL` and `ERR_LOG`; they all DM the same chat with their own prefixes (`[ai.openclaw.gateway]`, `[ai.hermes.gateway]`, etc.).

## Tunables (env vars)

| Variable | Default | What it controls |
|---|---|---|
| `WATCHDOG_LABEL` | required | The launchd `Label` of the bot to watch. |
| `WATCHDOG_ERR_LOG` | required | Path to the bot's stderr log; the smoking-gun tail. |
| `WATCHDOG_TG_BOT_TOKEN` | required | Watchdog's *own* Telegram bot token. |
| `WATCHDOG_TG_DM_CHAT_ID` | required | Dr Non's user id (DM destination). |
| `WATCHDOG_STATE` | `~/.council/watchdog/<label>.state.json` | Where to persist attempt count + heartbeat timer. |
| `WATCHDOG_MAX_ATTEMPTS` | `5` | Restart attempts before giving up and DMing. |
| `WATCHDOG_HEARTBEAT_HOURS` | `6` | Cadence of "still down" reminder DMs. |
| `WATCHDOG_LOG_TAIL_LINES` | `200` | How many trailing lines of the bot's err log to include in the give-up DM. |

## Sanity checks

- `python3 -m py_compile watchdog.py` — should succeed.
- Run once dry against a healthy bot:
  ```
  WATCHDOG_LABEL=ai.openclaw.gateway \
    WATCHDOG_ERR_LOG=/path/to/log \
    WATCHDOG_TG_BOT_TOKEN=... \
    WATCHDOG_TG_DM_CHAT_ID=... \
    python3 watchdog.py
  ```
  Expected: log line "is_running: True", no DM sent, exit 0.

## Operational note

If the watchdog itself crashes, that's a layer-3 problem (the watchdog isn't watching its watcher). For a hobby council, the launchd `KeepAlive` on the watchdog plist plus visual inspection of `~/.council/watchdog/openclaw.log` is sufficient. If you find yourself wanting a watchdog-of-watchdogs, you've outgrown this stack — graduate to a real PaaS supervisor.
