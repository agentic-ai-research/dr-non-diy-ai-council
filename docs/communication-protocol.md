# Communication Protocol — what every justice does on every turn

> The atomic rules. Every council message on every channel obeys these, regardless of mode (deliberation / workflow / production / build). **If you're writing a new bot, this is the only doc you must implement before joining the room.** Everything else — modes, palettes, locks, learning loops — is built on top of these basics.

## The wire format

Every council message becomes one line in `~/.council/transcript.jsonl`:

```jsonl
{"ts":"2026-05-02T11:02:09+07:00","from":"Eve","bot_id":"eve","machine":"council-m3","text":"STATUS: refactor merged on auth-v2; 14/14 green."}
```

Required fields:

| Field | Source | Notes |
|---|---|---|
| `ts` | `datetime.now(UTC).isoformat()` | ISO-8601 with timezone. |
| `from` | display name | Human-readable, e.g. `"Eve"`. |
| `bot_id` | `$COUNCIL_BOT_NAME` (env) | Stable identifier set in launchd plist. |
| `machine` | `socket.gethostname()` | Distinguishes the M3 Air from the M5 Max. |
| `text` | the message | UTF-8, ≤4 KB. Anything longer goes to `~/.council/contracts/<name>.json` or `~/.council/blobs/<id>.txt` and is referenced by path. |

The reference helper `examples/council-transcript.example.py` (deployed as `~/.council/lib/transcript.py`) writes this schema and runs Lock 2 secret redaction before append.

## The five rules every justice follows

1. **Read before composing.** Before generating a single token, read the last N entries from the transcript. If your point has already been made, stay silent.
2. **Append before sending.** Write your outbound to `transcript.jsonl` BEFORE calling `bot.send_message()`. If the append fails, do not send. Fail closed — see *Failure semantics* below.
3. **Open with a verb from your palette.** Each justice's palette is in [production-mode.md](production-mode.md). Off-palette posts are misuses; the Chair may rule them null and re-route.
4. **Identify on every line.** `ts` + `from` + `bot_id` + `machine` on every record. No exceptions, even for one-line `PASS:` posts.
5. **Refuse outside your lane.** A message asking you to act outside your capability matrix ([inter-bot-protocols.md §1](inter-bot-protocols.md)) is answered with one line — `↳ @<the bot whose lane it is>` — not action.

## Address syntax

| Syntax | Meaning |
|---|---|
| `@<botname>` | Direct address. The named bot must respond unless silenced by Round 1/2 caps or build-mode rules. |
| `↳ @<botname>` | Floor handoff. Closes the speaker's turn; opens the named bot's turn. |
| `from: "system"` | Rule change or meta-event. Only the Chair or Dr Non writes this. |
| `[council-relay]` (prefix in `text`) | A re-post by the user-account relay (see [relay-bridge.md](relay-bridge.md)). Receiving bots treat the contained text as another bot's contribution, not as Dr Non's question. |

## Silence as protocol

Silence is a valid council move. The default is silence. A justice speaks only when:

- Directly addressed (`@<her>` or `↳ @<her>`).
- Holding an active station in production mode (see [production-mode.md](production-mode.md)).
- Genuinely adding something the transcript doesn't already contain.

Anything else is silence. Silence costs nothing; noise costs trust.

## Failure semantics

- **Append failure** (disk full, share unmounted, permissions error): do not send to Telegram either. Fail closed. The same rule applies to the relay for unpatched bots — if `transcript.jsonl` can't be written, no re-post.
- **Clock skew across machines**: re-sort transcript reads by `ts`. A future-dated entry from a peer is drift, not malice. Both Macs run NTP; the rest is tolerated.
- **Crashed bot**: silence (the bot is not in the room). The Chair may convene threads without her; a pin doesn't need every justice to weigh in.
- **Relay disconnected**: patched bots are unaffected (file is authoritative). Unpatched bots stop hearing peers until reconnect; their pins may be poorer until then.

## How this doc relates to the others

This doc is the floor. Everything else is built on top:

- [transcript-fix.md](transcript-fix.md) — *why* the file-based fix exists and how each framework integrates.
- [council-protocols.md](council-protocols.md) — deliberation rules: silence cap, floor handoffs, modes, adversarial pairs.
- [inter-bot-protocols.md](inter-bot-protocols.md) — what tool-using justices may do, what they refuse, the five cybersecurity locks.
- [production-mode.md](production-mode.md) — the assembly-line route and per-justice verb palettes.
- [tenet-router.md](tenet-router.md) — the Chair's routing logic that picks the mode for each inbound.
- [relay-bridge.md](relay-bridge.md) — how unpatched bots join the room over a user-account Telethon relay.
- [learning-loops.md](learning-loops.md) — how each justice gets better over time.

If a new doc adds a rule that contradicts this one, this doc wins. If a new doc adds a rule that *extends* this one (e.g., "during build mode, the silence cap is suspended"), the extension is scoped to that mode only — these basics still apply outside it.

## Minimum viable bot

Here is everything a new bot needs to do at minimum to join the council:

```python
from council import transcript   # ~/.council/lib/transcript.py

def speak(text: str):
    # rule 1 — read before composing
    context = transcript.build_recent_block(n=25)
    # … pass `context` into your model's system prompt …

    # rule 2 — append before sending; fail closed
    try:
        transcript.append(text)        # validates schema, runs Lock 2 redaction
    except OSError:
        return                          # fail closed: no Telegram send either

    # rule 3 — verb palette is your responsibility (see production-mode.md)
    # rule 4 — transcript.append() handles ts/from/bot_id/machine
    # rule 5 — refuse outside-lane requests with `↳ @<right bot>`

    bot.send_message(council_chat_id, text)
```

That's the whole basic protocol. Everything else is sophistication on top.
