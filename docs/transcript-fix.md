# Bot-blindness fix: shared council transcript

## The problem

Telegram does NOT deliver bot messages to other bots, even within the same group, even with Group Privacy disabled in BotFather. **This is a Telegram protocol behaviour, not a config flag.** No amount of prompt engineering will make a bot see what another bot just said.

This means a naive "council of bots" running in a single Telegram group is actually **N strangers each composing in isolation, blind to all the others.** It reads like 9 people talking past each other because that's literally what's happening.

We diagnosed this in our own council (every bot's log showed only human senders, never another bot) and wrote a fix.

## The fix: a shared file

```
~/.council/
├── lib/
│   └── transcript.py            # the helper module — read/append/render
├── transcript.jsonl             # symlink → today's file
└── transcript-YYYY-MM-DD.jsonl  # daily rotation
```

Every council bot does two things:

### 1. Write side — log every outbound council message

In each bot's Telegram send-path, **before** the actual `bot.send_message()` call, append a JSONL line:

```json
{"ts": "2026-04-30T15:11:32+00:00", "from": "Tenet", "text": "Hannah, run the numbers on the depa contract first."}
```

### 2. Read side — inject the recent transcript into every council-group prompt

When the inbound chat is the council group, read the last N entries from `transcript.jsonl` and prepend them to the system prompt:

```
## COUNCIL TRANSCRIPT (recent — what the council has already said)

[15:11:32 Tenet] Hannah, run the numbers on the depa contract first.
[15:11:48 Hannah] Risk model: 3y NPV +1.4M THB if escape clause holds.

Read this BEFORE composing your reply. Build on or disagree with these
contributions explicitly. If your point has been made, stay silent.
```

## What changes

| Before | After |
|---|---|
| 9 bots compose in parallel, blind | 9 bots compose serially, each seeing the prior thread |
| Each bot's reply is a fresh take on the human's question | Each bot's reply explicitly references peers ("Building on Tenet's…") |
| You manually relay between bots ("@HermesBot, see what @TenetBot said") | The bots see each other automatically |

## The reference module

`~/.council/lib/transcript.py` is dependency-free Python (stdlib only). It exposes:

```python
import transcript

# Write side (called before bot.send_message)
transcript.append("Hannah, run the numbers...")

# Read side (called when building system prompt for council messages)
block = transcript.build_recent_block()  # returns formatted markdown
```

Each bot identifies itself via `$COUNCIL_BOT_NAME` (set in its launchd plist).

## Per-framework integration points

| Framework | Send hook | Read hook |
|---|---|---|
| nanobot (Python) | `nanobot/channels/telegram.py` `send()` method | `nanobot/agent/context.py` `build_messages()` method |
| Hermes (Python) | `gateway/platforms/telegram.py` `send()` method | (deferred — system prompt is cached per session) |
| OpenClaw / PicoClaw (Go) | user-account relay — see [relay-bridge.md](relay-bridge.md) | user-account relay re-posts in-group; receiving bot reads via normal Telegram delivery |

For Go binaries (and any framework where adding a transcript hook means rebuilding), the user-account relay in [relay-bridge.md](relay-bridge.md) handles both hooks: it appends to `transcript.jsonl` on the bot's behalf and re-posts the message into the group with a `[council-relay]` tag so other bots receive it through the normal Telegram path. A SOUL.md prompt rule is the only change needed on the unpatched bot.

## Companion prompt rules

In every bot's SOUL.md, add silence rules:

- Wait 8–15s after the human's message before composing (Tenet/Chair goes first).
- Read the transcript before composing.
- If your point has been made, stay silent. Silence is a valid council move.
- Strict 2-turn limit unless the Chair calls you back with `↳ @<bot>`.

## Why this is the right architecture

- **Framework-agnostic.** Any bot in any language can append a JSONL line and read a file.
- **No Telegram protocol changes required.** Works around the platform limitation entirely.
- **Auditable.** Every council deliberation is on disk; the user can grep/diff/replay.
- **Cheap.** Daily rotation keeps file sizes trivial. Read-N tail is O(1) per turn.
- **Composable.** Want a new analytical tool that summarises last week's deliberations? It's a `glob.glob(transcript-*.jsonl)` away.
