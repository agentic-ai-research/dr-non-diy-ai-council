# SECURITY.md — credential discipline runbook

The one-page reference for the council's credential handling. The protocol-level rules are in [docs/inter-bot-protocols.md](docs/inter-bot-protocols.md) (Lock 2 secret redaction, Lock 3 per-bot keychain) and [docs/communication-protocol.md](docs/communication-protocol.md). This doc is the *runbook* — the page you re-read in 60 seconds when something has gone wrong.

## Where secrets must live

**macOS Keychain only.** One Keychain item per bot, per credential type. The naming convention:

```
council-<bot>-telegram     # the bot's Telegram bot-API token
council-<bot>-nim          # NVIDIA NIM API key
council-<bot>-openrouter   # OpenRouter (failover) key
council-<bot>-anthropic    # Anthropic API key (Eve, LOL only)
council-<bot>-groq         # Groq API key
council-<bot>-twitter      # per-account Twitter/X bearer token
council-<bot>-linkedin     # per-account LinkedIn token
council-<bot>-youtube      # per-channel YouTube API key
```

### Add a secret to Keychain

```bash
security add-generic-password \
    -a "$USER" \
    -s "council-<bot>-<credential>" \
    -w \
    -U
# At the prompt, paste the token. Press Enter. Confirm by pasting again.
```

The token never appears on the command line, in shell history, or in any file. It lives only in the encrypted Keychain database.

### Read a secret (from a wrapper script)

```bash
security find-generic-password -a "$USER" -s "council-<bot>-<credential>" -w
```

Use [`examples/security/keychain-wrapper.sh`](examples/security/keychain-wrapper.sh) as the canonical wrapper that reads → exports → execs the bot binary.

## Where secrets must NOT live

| ❌ | Why |
|---|---|
| `.env` files (any) | Plaintext on disk; one wrong `cat` and they're gone. |
| launchd plist `<key>EnvironmentVariables</key>` blocks | Plaintext on disk; readable by any process the user owns. |
| Shell history (using `--token=…` on the command line) | Persisted to `~/.zsh_history` / `~/.bash_history`. |
| Any log file | Append-only and tempting to share. Use the redaction filter ([examples/security/redact-tokens.py](examples/security/redact-tokens.py)). |
| Any chat — Telegram, Slack, Claude conversation, ChatGPT, Discord | Logged on the platform's servers, in your client's local cache, in screenshots. |
| URL parameters | Logged in server access logs and in browser referrer headers. |
| Any code file in any repo, including private ones | One `git push` to the wrong remote and the secret is on GitHub. |

## Defense in depth — redact at write time

Even if a token escapes the Keychain through a logging mistake, [`examples/security/redact-tokens.py`](examples/security/redact-tokens.py) is a `logging.Filter` that scrubs known credential shapes from log records *before* they hit any handler. Attach it to every Python logger that touches HTTP responses, model output, or any text that could embed a credential.

The patterns are the same as Lock 2 in the transcript reference: `bot<digits>:<35-char>`, `sk-…`, `sk-ant-…`, `ghp_…`, `xox?-…`, `AKIA…`, `Bearer …`, `password=…`. Add new patterns to `_PATTERNS` in `redact-tokens.py` whenever a new credential shape enters the council.

## When a credential leaks — the five-step runbook

You've pasted a token, found one in a log, or seen one shared. **Treat the credential as compromised regardless of who saw it.** Then:

1. **Revoke at source — immediately.**
   - **Telegram bot tokens:** open `@BotFather` in Telegram → `/mybots` → tap the bot → `API Token` → `Revoke current token`. BotFather generates a fresh one on the same screen.
   - **OpenAI / Anthropic / NIM / OpenRouter / Groq:** the provider's web UI → API keys → Revoke / Delete.
   - **GitHub PAT:** [github.com/settings/tokens](https://github.com/settings/tokens) → Revoke.
   - **AWS:** IAM console → Users → Security credentials → Make inactive / Delete.
2. **Generate a fresh credential** at the same UI. Copy it once, to the system clipboard.
3. **Store the fresh credential in Keychain — never paste it anywhere else:**
   ```bash
   security add-generic-password -a "$USER" -s "council-<bot>-<credential>" -w -U
   ```
   Paste at the interactive prompt. Confirm. Done.
4. **Scrub the leak source.**
   - **Log file:** `> /path/to/leaky.log && chmod 600 /path/to/leaky.log`. Truncates and locks down.
   - **Chat:** report to the chat owner; rotation is the only real fix (the message stays in their database forever).
   - **Repo:** rotation first; if you must remove from history, `git filter-repo` with the pattern, then force-push and notify any collaborators who pulled.
5. **Add the leak shape to the redaction filter** if it's a new pattern, so it can't recur silently. Edit `_PATTERNS` in [`examples/security/redact-tokens.py`](examples/security/redact-tokens.py).

## When in doubt, treat it as leaked

Rotation is cheap. Remediation after misuse is not.

A bot whose token leaks: an attacker can read every message that bot can read (the chat history, including DMs forwarded into the council group), can post on the bot's behalf, can delete messages, and — if the bot is admin of a group — can kick members or change settings. Telegram's privacy model doesn't bound this; only revocation does.

Five minutes to rotate. Days to weeks to clean up an actual misuse.

## Operational hygiene

- **`chmod 600`** any log file the council writes. Default is often `644`, which means any user on the system can read it.
- **`launchctl bootout` and `bootstrap`** any bot whose credentials you've rotated. The wrapper re-reads the Keychain at boot; it does not pick up changes hot.
- **Don't share screenshots** of terminal windows or chats without redacting. macOS's screenshot tool has no automatic credential detection.
- **Don't paste log excerpts into chats with anyone — including AI assistants — without scrubbing for tokens first.** The Lock 2 redaction patterns above are good first-pass; manual review is the second.

## Cross-reference

- [docs/inter-bot-protocols.md §6](docs/inter-bot-protocols.md) — the five Locks, including this redaction policy.
- [docs/communication-protocol.md](docs/communication-protocol.md) — the floor every justice respects, including the prohibition on echoing credentials in transcripts.
- [docs/resilience.md](docs/resilience.md) — provider failover including per-bot key rotation when a key is revoked while the bot is in flight.
