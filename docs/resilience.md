# Resilience — surviving provider outages and bot crashes

> Companion to [inter-bot-protocols.md](inter-bot-protocols.md), [multi-task.md](multi-task.md), [task-lifecycle.md](task-lifecycle.md). The original protocol stack handled **single-bot** failures (silence rule, fail-closed transcript). This doc closes the gap that opened on **2026-04-28 8:20 PM**, when OpenClaw's gateway began an unrecoverable restart loop and stayed down for 30+ hours while the watchdog spammed the council with identical alerts every 5 minutes. Six bots went dark together; nobody told Dr Non in a way he'd notice; the room was half-empty and didn't know it.

## Three layers, layered

```
Layer 1 — Endpoint failover.       per-bot     try the next provider on 401/429/timeout
Layer 2 — Watchdog discipline.     per-bot     stop spamming after N failures; DM Dr Non
Layer 3 — Council degraded mode.   council-wide  Tenet declares; room knows it's at half capacity
```

Each layer activates when the one below it isn't enough. Layer 1 catches transient provider blips. Layer 2 catches binary crashes the harness can't recover from. Layer 3 catches the case where multiple bots are down at once and the room needs to operate degraded.

---

## Layer 1 — Per-bot endpoint failover

### The schema (extended `policy.example.json`)

Every bot's entry can carry an ordered `endpoints` array. The harness walks it on 401 / 429 / timeout, in order, until one returns 200.

```json
"otto": {
  "tools": ["telegram-send", "web-fetch", "email", "calendar", "fs-read"],
  "endpoints": [
    { "provider": "nvidia-nim",   "model": "qwen3-480b",     "key_ref": "council-otto-nim" },
    { "provider": "openrouter",   "model": "qwen-2.5-72b",   "key_ref": "council-otto-openrouter" },
    { "provider": "together",     "model": "qwen2.5-72b",    "key_ref": "council-otto-together" },
    { "provider": "ollama-local", "model": "qwen2.5:72b",    "host": "http://localhost:11434" }
  ],
  "constraints": { ... }
}
```

Defaults:
- **Backoff**: 5 s between endpoints.
- **Sticky duration**: once on a fallback, stay there for 5 minutes before retrying primary. Avoids thrash.
- **Local Ollama as last resort**: every bot SHOULD list a local fallback. Slower, but works offline. The M3 Air has the headroom.

### The new palette verb — `FAILOVER:`

When the bot drops to a fallback, she logs it once in the transcript so the room knows the contribution came from a degraded source:

```
[#bangkok-contract] Otto: FAILOVER: nim → openrouter
  reason: 401
  latency-added-ms: 800
```

This is one line per failover event, not per call. If Otto stays on OpenRouter for 5 minutes of work, that's one `FAILOVER:` at the start, not fifteen.

The verb is **additive** to the bot's existing palette ([production-mode.md](production-mode.md)) and lives outside the per-bot palette tables — every bot with `endpoints` may post `FAILOVER:` regardless of role.

---

## Layer 2 — Watchdog discipline

The April 28–30 watchdog spammed *"Gateway DOWN — restart failed"* every 5 minutes for 30 hours. That's a watchdog failure, not just a gateway failure. A good watchdog tells you a fact at most once per state change.

### The rules every council watchdog follows

1. **Try restart up to N times** (default `N=5`) with exponential backoff (`30s, 60s, 120s, 240s, 480s`).
2. **After N failures, stop trying.** The binary is broken; a sixth attempt won't help.
3. **DM Dr Non, do not post to council.** One Telegram DM with a one-line summary plus a 200-line tail of the error log:
   ```
   [GATEWAY-DOWN] ai.openclaw.gateway — 5 restart attempts failed.
   Last error: 401 Unauthorized (NIM key likely expired or revoked).
   Log tail: <link or attached>
   ```
4. **Heartbeat cadence after stopping**: one DM every 6 hours, no more. *"Still down. 23h since first failure."* Single line; same chat as the original DM.
5. **On recovery (gateway returns to green), one final DM**: *"Recovered. Down for 23h 45m."* Then silence again.

The watchdog **never** posts to the council group on a third or later identical failure. The council group is for working bots, not error spam.

### Reference implementation

[examples/watchdog/watchdog.py](../examples/watchdog/watchdog.py) — stdlib + Telegram Bot API, ~140 lines, drop-in. Reads `launchctl print` for the bot's service status; restarts with backoff; DMs on stop and on recovery.

---

## Layer 3 — Council degraded mode

When ≥3 bots are on Layer-1 fallback, or any 1 bot is fully down at Layer 2, the council is operating below design capacity. Tenet must say so once.

### Declaration

At the top of the next thread (or at the start of the next morning briefing if no inbound is queued), Tenet posts:

```
MODE: DEGRADED
DOWN: [otto, ana]              # fully down (Layer 2 stopped trying)
FALLBACK: [civic, aviva]       # on a non-primary endpoint (Layer 1)
IMPACT: people-side actions blocked; ethics axis at half-rate
```

The declaration:
- Goes in the canonical transcript (not just the watchdog DM).
- Is **picked up by [hourly-digest.py](../examples/analytics/hourly-digest.py)** as a top-level heading on every digest until cleared. Dr Non sees it without scrolling.
- Stays until Tenet clears it: `MODE: NORMAL  DOWN: []  FALLBACK: []`.

### Room behavior under degraded mode

| Concern | Rule |
|---|---|
| Pinning threads | Allowed — the room continues. Note the missing reviewers' absence in the pin: *"🪑 PIN: take it. (Ana down — duty axis not reviewed; revisit when she returns.)"* |
| Public posting | **Forbidden.** No `BENCH:` graduation, no auto-posts. Reputational risk x degraded room = no. |
| Standing orders Otto owns | Auto `STAND-DOWN:` until Otto recovers. Resume on `MODE: NORMAL`. |
| New high-stakes decisions | BENCH first; don't pin a values-trade-off without the duty/utility pair. |
| Builder threads (Eve, LOL) | Continue normally — builders run on Claude Sonnet 4.5, not NIM, and are unaffected by NIM outages. |

### Recovery

When all bots return to primary endpoints, Tenet declares `MODE: NORMAL` once. Standing orders resume from their last `STAND-DOWN:`. Public posting unlocks. The hourly digest stops flagging.

---

## Worked example — what April 28 should have looked like

Below is the same outage, replayed against the new protocol. *Italics* are events that didn't happen on the actual timeline; **bold** is the difference.

```
8:20 PM  Watchdog: ai.openclaw.gateway — restart attempt 1/5 failed (401).
                   Backing off 30s.
8:21 PM  Watchdog: restart attempt 2/5 failed (401). Backing off 60s.
8:22 PM  Watchdog: restart attempt 3/5 failed (401). Backing off 120s.
8:24 PM  Watchdog: restart attempt 4/5 failed (401). Backing off 240s.
8:28 PM  Watchdog: restart attempt 5/5 failed (401). STOPPING.

8:28 PM  Watchdog → DM Dr Non:
         [GATEWAY-DOWN] ai.openclaw.gateway — 5 restart attempts failed.
         Last error: 401 Unauthorized (NIM key likely expired or revoked).
         Log tail attached.

8:28 PM  Tenet (council group):
         MODE: DEGRADED
         DOWN:     [otto]
         FALLBACK: []
         IMPACT:   people-side actions (email, calendar, drive) blocked.
                   Public posting suspended. Standing orders STAND-DOWN.

[at this point Otto-dependent workflows redirect or pause — the room
 keeps running on the other 11 justices]

[over the next minutes, NIM-backed bots also fail; layer 1 fails them
 over to Layer 2, which alerts and Tenet updates the declaration]

8:35 PM  Tenet: MODE: DEGRADED  DOWN: [otto, ana, civic, aviva, bob]
                FALLBACK: [tenet, hannah on local-ollama]
                IMPACT: NIM provider down for the bench.

2:28 AM  Watchdog → DM Dr Non:
         Still down. 6h since first failure.

[Dr Non rotates the NIM key in the morning]

8:00 AM  Watchdog: gateway recovered. Notifying.
8:00 AM  Watchdog → DM Dr Non:
         Recovered. Down for 11h 32m.
8:00 AM  Tenet: MODE: NORMAL  DOWN: [] FALLBACK: []. Standing orders resuming.
```

One DM to wake up to. Not 360 watchdog spam messages. The room knew it was degraded, paused public posting, and kept going on the bots that worked.

---

## Implementation order

1. **Watchdog rate-limit + DM escalation** ([examples/watchdog/watchdog.py](../examples/watchdog/watchdog.py)). Smallest blast radius, biggest immediate-quality-of-life win. Land first.
2. **`endpoints` array in `policy.example.json`** for at least Otto (the bot that just went down). Per-framework loaders in M1 of [ROADMAP.md](../ROADMAP.md) pick this up; until then, document the contract.
3. **`FAILOVER:` palette verb** in [production-mode.md](production-mode.md) — written here, applied per-bot when the loaders ship.
4. **`MODE: DEGRADED` declaration** in Tenet's SOUL.md. Until Tenet's harness picks this up, Dr Non can post the declaration manually after a watchdog DM.
5. **Hourly digest awareness** of `MODE: DEGRADED` — small extension to [hourly-digest.py](../examples/analytics/hourly-digest.py); add a top-of-file banner whenever the most recent `MODE:` declaration is `DEGRADED`. Trivial when ready.

Steps 1, 4, 5 are doable with what's in this repo. Steps 2 and 3 are policy+documentation here; harness adoption is M1.

---

## What this doc does NOT do

- **Doesn't change the JSONL transcript schema.** `FAILOVER:` and `MODE: DEGRADED` are message-text conventions, not new fields.
- **Doesn't introduce a new justice.** Failover is per-bot infrastructure, not a new role.
- **Doesn't replace [inter-bot-protocols.md](inter-bot-protocols.md) Lock 3.** Per-bot keychain isolation still applies — each endpoint's `key_ref` is its own keychain item.
- **Doesn't gate Eve and LOL.** Builders run on Claude Sonnet 4.5 outside NIM; NIM outages don't touch them. Their resilience is the Anthropic API's resilience.
- **Doesn't enforce.** Like the rest of the policy stack, this binds in code only when M1 (per-framework loaders) ships. Until then, the rules above are convention.
