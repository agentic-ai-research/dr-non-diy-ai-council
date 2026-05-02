# `examples/security/` — credential discipline reference

Two drop-in helpers that together close the most common credential-leak path on this council: secrets ending up in log files or in launchd plist files. Read [SECURITY.md](../../SECURITY.md) at the repo root for the runbook; this directory is the *implementation*.

| File | Purpose |
|---|---|
| [`redact-tokens.py`](redact-tokens.py) | A `logging.Filter` that scrubs credential-shaped strings *before* they hit any log handler. Drop into any Python logger. |
| [`keychain-wrapper.sh`](keychain-wrapper.sh) | A bash wrapper that launchd plists run *instead of* the bot binary, so the token is read from Keychain at boot and never lives in the plist file or any shared `.env`. |

## How to install

```bash
mkdir -p ~/.council/lib
cp examples/security/redact-tokens.py    ~/.council/lib/
cp examples/security/keychain-wrapper.sh ~/.council/lib/
chmod +x ~/.council/lib/keychain-wrapper.sh
```

## Wiring the redaction filter into a Python bot

### Direct API

```python
import logging
import sys
sys.path.insert(0, "/Users/YOU/.council/lib")
from redact_tokens import RedactingFilter   # noqa: E402

# Attach to whichever handlers the bot uses
handler = logging.StreamHandler()
handler.addFilter(RedactingFilter())
logging.getLogger().addHandler(handler)
```

The filter operates on `record.msg` and `record.args`, so `logger.info("token: %s", token)` and `logger.info(f"token: {token}")` are both protected.

### dictConfig

```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "redact_tokens.RedactingFilter"}},
    "handlers": {
        "console": {
            "class":   "logging.StreamHandler",
            "filters": ["redact"],
            "level":   "INFO",
        },
        "file": {
            "class":    "logging.FileHandler",
            "filename": "/Users/YOU/.eve/eve.log",
            "filters":  ["redact"],
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
}
import logging.config
logging.config.dictConfig(LOGGING)
```

### Hook into a third-party HTTP client (httpx, requests, aiohttp)

Each of these uses Python's stdlib `logging`. Attach the filter to the relevant logger:

```python
logging.getLogger("httpx").addFilter(RedactingFilter())
logging.getLogger("urllib3").addFilter(RedactingFilter())
logging.getLogger("aiohttp.client").addFilter(RedactingFilter())
```

That's how Eve's leak class gets fixed at the source — `httpx` (or whichever client she uses) was logging request URLs with the token embedded; the filter scrubs it before write.

## Wiring the keychain wrapper into a launchd plist

### One-time: store the secret in Keychain

```bash
security add-generic-password \
    -a "$USER" \
    -s "council-eve-telegram" \
    -w \
    -U
# At the prompt, paste the token. Press Enter. Confirm. Done.
```

The token now lives in macOS Keychain, only readable by your user (and by processes you authorize). It is **not** in any file, env var, plist, or shell history.

### Update the plist

Replace any inline `Token` env var with the wrapper:

```xml
<key>ProgramArguments</key>
<array>
  <string>/Users/YOU/.council/lib/keychain-wrapper.sh</string>
  <string>council-eve-telegram</string>          <!-- keychain service -->
  <string>EVE_TG_TOKEN</string>                  <!-- env var to set    -->
  <string>/usr/local/bin/eve-coder</string>      <!-- the real binary   -->
  <string>--config</string>
  <string>/Users/YOU/.eve/config.yml</string>
</array>
```

Reload the plist:

```bash
launchctl bootout    "gui/$(id -u)/ai.eve-coder" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/ai.eve-coder.plist
```

Eve now starts with `EVE_TG_TOKEN` set in her environment, and nowhere else.

## Verify

### Redaction filter — self-test

```bash
python3 ~/.council/lib/redact-tokens.py
# Expected: a list of synthetic samples mapped to redacted versions, ending with "self-test OK".
```

### Keychain wrapper — dry test

```bash
~/.council/lib/keychain-wrapper.sh council-eve-telegram EVE_TG_TOKEN /usr/bin/env | grep '^EVE_TG_TOKEN='
# Expected: one line, EVE_TG_TOKEN=<the actual token>.
# (We're using `env` as the "binary" — it just prints the env vars and exits.)
```

If the wrapper prints `no secret found for service=council-eve-telegram`, the keychain item is missing — re-run the `security add-generic-password` step.

### Confirm the bot itself isn't logging tokens

After Eve restarts:

```bash
grep -E 'bot[0-9]+:|sk-|Bearer ' ~/Brain/heartbeat.log /Users/YOU/.eve/*.log 2>/dev/null
# Expected: no output, or only the literal placeholder strings like "bot<TG_TOKEN_REDACTED>".
```

If you see real-looking tokens, the filter isn't attached to the right logger. Check which logger the HTTP client uses — `import logging; print(logging.getLogger().manager.loggerDict.keys())` after the bot has run a couple of requests.

## What this directory does NOT do

- **Doesn't rotate existing leaked tokens.** Use the runbook in [SECURITY.md](../../SECURITY.md) — revoke at source, generate fresh, store in Keychain.
- **Doesn't scrub historical log files.** `> ~/Brain/heartbeat.log && chmod 600 ~/Brain/heartbeat.log` does that. The redaction filter only protects future writes.
- **Doesn't authorize processes.** macOS Keychain requires the running process to be signed by an authorized identity for unattended access. If `security find-generic-password` prompts you the first time, click "Always Allow" — that's the trust grant.
