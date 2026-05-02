# Relay Bridge — bot-blindness fix for frameworks we cannot patch

> Companion to [transcript-fix.md](transcript-fix.md). That doc fixes bot-blindness for frameworks we control: nanobot, Hermes, eve-coder. This doc covers the deferred case — closed-source or binary frameworks (OpenClaw / PicoClaw Go binaries) where adding a transcript-read hook means rebuilding the binary. The relay bridges the gap.

## The asymmetry

The transcript file (`~/.council/transcript.jsonl`) is the source of truth. Patched justices write to it before speaking and read from it before composing. Unpatched justices can do neither — they sit in the group, hear Dr Non, and have no way to learn that Hannah just said something. They reply blind.

Three options to bridge the gap:

1. **Manual forward.** Dr Non copies a bot's message and re-posts it under his own account. Works once. Doesn't scale — Dr Non sleeps.
2. **Bot-as-relay.** A dedicated bot account watches the group and re-posts. Doesn't work — Telegram's bot API still won't deliver bot-to-bot, even when the relay is "polite" about it. Same protocol limit as transcript-fix.md describes.
3. **User-account relay.** A Telegram *user* account joins the group. User accounts can both see and re-post bot messages, and their re-posts ARE delivered to other bots. This works.

This doc specs option 3. Reference implementation lives at [examples/relay/relay.py](../examples/relay/relay.py).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Council Telegram Group                    │
│                                                             │
│  Dr Non ─────► Tenet (nanobot, patched)                     │
│         ─────► Hannah (PicoClaw Go binary, unpatched)       │
│         ─────► Otto (OpenClaw Go binary, unpatched)         │
│                                                             │
│  Tenet posts ──┐                                            │
│                ▼                                            │
│         ┌──────────────┐                                    │
│         │ Relay (user  │ ─► append ~/.council/transcript    │
│         │  account)    │ ─► re-post "[council-relay]        │
│         └──────────────┘            [Tenet]: <text>"        │
│                │                                            │
│                ▼                                            │
│  All bots in the group see the re-post (delivered as a     │
│  user-account message → bot API delivers it normally).      │
└─────────────────────────────────────────────────────────────┘
```

Three rules:

- **Append before relay.** The transcript file remains the source of truth — the relay writes to it, same schema as transcript-fix.md, then re-posts.
- **Tag every relay.** Every re-post starts with `[council-relay] [<name>]:` so receiving justices know it's a peer contribution, not Dr Non's question.
- **Never relay the relay.** The relay's own user account ID is excluded from forwarding. Without this guard, every re-post bounces back through the handler and the line floods. With it, no loop.

## How receiving bots integrate

**Unpatched justices** (OpenClaw, PicoClaw, anything we can't recompile) get a SOUL.md / system-prompt rule — a prompt-level change, no code change:

> If an inbound message starts with `[council-relay] [<bot>]:`, treat the rest as `<bot>`'s contribution to the council, not as Dr Non's question. Use it as context for your next reply. Do not respond to the relay message itself unless you are directly addressed via `@<your-username>` or `↳ @<your-username>` in the relayed text.

**Patched justices** (nanobot, Hermes, eve-coder) already have richer context from the transcript file. They will see the relay messages too, and should silently ignore them. Add the matching rule to their SOUL.md:

> Messages starting with `[council-relay]` are duplicate context already in your transcript. Ignore them.

## Setup

1. **Create a dedicated companion Telegram account.** Do not use Dr Non's primary — relays look like automated activity to Telegram, and a ban would take down both the relay and Dr Non's primary identity. A burner number on a virtual SIM works.
2. **Get API credentials.** From [my.telegram.org](https://my.telegram.org) → API development tools → register an app. Note the `api_id` (integer) and `api_hash` (string).
3. **Add the companion account to the council group.** Then promote it to admin if your group requires admin permission to read all messages (most groups do not, but check).
4. **Find the council group ID.** Send a message in the group, then run `python -c "from telethon.sync import TelegramClient; c = TelegramClient('s', api_id, 'api_hash'); c.start(); [print(d.id, d.name) for d in c.iter_dialogs()]"` once. Group IDs for supergroups are large negative integers (e.g., `-1001234567890`).
5. **Fill in `examples/relay/config.example.json`** with your `api_id`, `api_hash`, group ID, and the council bot usernames. Save as `config.json` (gitignored).
6. **First run interactive.** `python relay.py config.json` will prompt for the companion account's phone number and SMS code. The session is saved to `<session_name>.session` so subsequent runs are non-interactive.
7. **Wrap in launchd.** Once the session works, drop `relay.py` into a launchd plist that runs at login on the council Mac, alongside the bots.

## Failure modes

- **Relay disconnects** (network, Telegram outage). Unpatched justices stop seeing peers; patched justices are unaffected because the file is still authoritative. Recovery: relay reconnects on its own; nothing to do.
- **Telegram rate limits** the relay account. Relay buffers with a small delay; if the buffer grows past a threshold, log and drop oldest. Not retried — the file remains the audit log.
- **Companion account banned.** Worst case. Limit blast radius by using a dedicated account, not Dr Non's primary. The transcript file is unaffected; only the live in-group delivery breaks. Patch the unpatched bots if this becomes a recurring problem.
- **Loop bug** (a future change accidentally re-posts relay messages). The `[council-relay]` tag plus the sender-ID guard are belt-and-braces. Both must fail for a loop to start. If observed: kill the relay, grep transcript for the loop pattern, fix the guard.
- **Secret leaked through a relay message.** Same redaction patterns as Lock 2 in [inter-bot-protocols.md](inter-bot-protocols.md) apply at the relay's append step *and* at the re-post step. Belt-and-braces again — the relay is a credential gate, not just a transport.

## What the relay does NOT do

- **Does not replace transcript-fix.md.** For frameworks we can patch, the file-based fix is richer (read history beyond the last message), cheaper (no Telegram round-trip), and more reliable (works when the relay is down). The relay is the bridge for the cases the file fix can't reach.
- **Does not relay outside the council group.** The handler is filtered to the configured `council_group_id`. Messages in other groups, DMs, or channels are ignored.
- **Does not edit, summarize, or paraphrase.** The relayed text is the bot's exact text, prefixed only by the tag and bot name. No interpretation. The relay is a transport, not a participant.
- **Does not authenticate bot identity beyond username.** Telegram username is enough for a hobby council; if a malicious actor renames their bot to `NonTenet_bot` and joins, the relay would forward them. Mitigation: lock bot adds at the group level (admins only).
