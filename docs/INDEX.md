# The Council Protocol Stack

Twelve protocol docs. ~2,500 lines. The IP behind the council. Read top-down for orientation; jump to the right layer when you have a specific question.

## Reading paths

### "I'm new — what is this?"

1. [README.md](../README.md) — project overview + the Manus comparison.
2. [council-soul.md](council-soul.md) — the mindset every justice carries (Musk · Bezos · Norman · Pinker · 3 Cs · Flow).
3. [justice-roles.md](justice-roles.md) — the bench, by framework strength.

### "I'm writing a new bot."

1. [communication-protocol.md](communication-protocol.md) — **the floor.** What every justice does on every turn. The 12-line minimum-viable-bot is here.
2. [justice-roles.md](justice-roles.md) — which justice does what; what each refuses.
3. [inter-bot-protocols.md](inter-bot-protocols.md) — the capability matrix; what each bot may and must-not do.
4. [production-mode.md](production-mode.md) — the per-bot adaptive verb palette.

### "I'm running a council."

1. [transcript-fix.md](transcript-fix.md) — the file-based bot-blindness solution.
2. [relay-bridge.md](relay-bridge.md) — Telethon user-account relay for unpatchable bots.
3. [inter-bot-protocols.md §6](inter-bot-protocols.md) — the five cybersecurity locks.
4. [multi-task.md](multi-task.md) — concurrent threads, standing orders, public-account bench gates.

### "I want to extend with new modes / verbs."

1. [tenet-router.md](tenet-router.md) — the Chair's routing decision tree.
2. [production-mode.md](production-mode.md) — assembly-line palette per justice.
3. [multi-task.md](multi-task.md) — standing orders + public-account rules.

### "I want to know how the council learns."

1. [learning-loops.md](learning-loops.md) — three loops at three cadences; per-bot reward signals.
2. [examples/learning/reflect.py](../examples/learning/reflect.py) — the cron job that builds the exemplar library.
3. [examples/analytics/hourly-digest.py](../examples/analytics/hourly-digest.py) — noN's hourly Obsidian digest.

## The twelve docs

| Doc | Layer | What it answers |
|---|---|---|
| [council-soul.md](council-soul.md) | Mindset | *How does every justice **think**?* |
| [justice-roles.md](justice-roles.md) | Role | *Which justice does **what**?* |
| [communication-protocol.md](communication-protocol.md) | Floor | *How does every justice **speak**?* |
| [transcript-fix.md](transcript-fix.md) | Transport | *Why a file, not a Telegram channel?* |
| [relay-bridge.md](relay-bridge.md) | Cross-Mac | *How does the M5 Max join?* |
| [council-protocols.md](council-protocols.md) | Deliberation | *How does the Court **argue**?* |
| [tenet-router.md](tenet-router.md) | Routing | *Which mode for **this** inbound?* |
| [inter-bot-protocols.md](inter-bot-protocols.md) | Action | *Who calls tools? What's logged?* |
| [production-mode.md](production-mode.md) | Production | *How does the assembly line ship?* |
| [multi-task.md](multi-task.md) | Concurrency | *N threads, standing orders, public accounts.* |
| [learning-loops.md](learning-loops.md) | Learning | *How does each justice **get better**?* |
| [bot-personalities.md](bot-personalities.md) | Voice | *What does each justice **sound like**?* |

## The layered hierarchy

```
council-soul.md          ← mindset (the why)
        │
        ▼
justice-roles.md         ← what each justice pulls (the what)
        │
        ▼
communication-protocol.md ← how to speak at all (the floor)
        │
        ▼
[modes, action rules,
 learning, relay,
 multi-task]              ← built on the floor
```

A new contributor reads top-down and stops where their question is answered. A new bot author starts at the floor (`communication-protocol.md`) and reads only the layers her work touches. Dr Non can re-read the soul on any morning to remember why.

## Reference implementations

The protocol stack is the IP; these are the reference codes that prove the protocols work end-to-end:

| File | Purpose |
|---|---|
| [examples/council-transcript.example.py](../examples/council-transcript.example.py) | The `~/.council/lib/transcript.py` reference — `append()` with Lock 2 redaction; `read_recent()`; identity fields. |
| [examples/relay/relay.py](../examples/relay/relay.py) | Telethon user-account relay — bridges OpenClaw/PicoClaw Go binaries into the transcript world. |
| [examples/learning/reflect.py](../examples/learning/reflect.py) | Cron-driven reflection — pins → per-bot exemplar files. |
| [examples/analytics/hourly-digest.py](../examples/analytics/hourly-digest.py) | noN's hourly Obsidian digest. |
| [examples/policy/policy.example.json](../examples/policy/policy.example.json) | Capability-matrix schema for per-framework loaders. |
| [infra/tailscale-acl.json](../infra/tailscale-acl.json) | Lock 1 — two-Mac ACL spec. |
| [.github/workflows/lint.yml](../.github/workflows/lint.yml) | Lock 5 — CI lint blocking exec-of-message-content. |

## Where to send patches

PRs against [main](https://github.com/agentic-ai-research/dr-non-diy-ai-council). The CI lint is the only required check; the rest is Dr Non's review. New justices need a palindrome name (this is non-negotiable) and a row added to [README.md](../README.md), [justice-roles.md](justice-roles.md), and [inter-bot-protocols.md §1](inter-bot-protocols.md).
