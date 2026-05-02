# Per-handle identity routing

The council has thirteen justices but typically two or three frameworks (OpenClaw, Hermes, PicoClaw, Nanobot, eve-coder). One framework gateway often serves *multiple* Telegram bot accounts — Otto and Otter both run on OpenClaw; Radar and a research-second-brain run on Hermes; Hannah and Ada both run on PicoClaw.

If the framework reads a single `SOUL.md` regardless of which Telegram handle the inbound came in on, every bot identifies the same way. The 2026-05-02 incident was exactly this: `@DrNonOpenClaw_bot` (Otter, the personal assistant) and `@NonOtto_bot` (Otto, the council executor) both read `~/.openclaw/SOUL.md`, which says *"Your name is Otto"*. So Otter answered DMs as Otto.

The fix is **per-handle identity routing**: at request time, the harness looks up which Telegram handle the inbound is for, and loads the matching identity. Two implementations, one per framework family.

## Pattern A — multi-agent (OpenClaw, eve-coder)

OpenClaw supports `~/.openclaw/agents/<agent>/`. Today there's only one (`main`). To split:

```
~/.openclaw/agents/
├── otto/
│   ├── SOUL.md       ← council identity, palette, lane
│   └── IDENTITY.md   ← optional voice details
├── otter/
│   ├── SOUL.md       ← personal-assistant identity, redirects council asks
│   └── IDENTITY.md
└── main/             ← deprecated; retire after migration
```

Per-bot SOULs in this directory: see [`per-handle/`](per-handle/) for templates filled in for Otto and Otter.

OpenClaw routes by Telegram handle via `agent.json` per agent — set the `telegramUsername` to the handle and the gateway dispatches accordingly. See [`openclaw-multi-agent.example.md`](openclaw-multi-agent.example.md) for the migration steps.

## Pattern B — personalities map (Hermes, Nanobot)

Hermes's `config.yaml` already has a `personalities:` block — but on this Mac it's currently `personalities: {}` (empty). That's why every Hermes-served bot falls through to the generic "direct senior technical advisor" SOUL.

Populate it with one entry per handle:

```yaml
personalities:
  "@NonRadar_bot":
    name: "Radar"
    role: "Researcher"
    soul_path: "~/.hermes/personalities/radar.SOUL.md"
    palette: ["FACT:", "EVIDENCE:", "DEDUCE:", "NULL:"]

  "@NonSecondBrain_Bot":
    name: "Aviva"
    role: "Strategist"
    soul_path: "~/.hermes/personalities/aviva.SOUL.md"
    palette: ["STRATEGIC:", "POSITION:", "LONG-VIEW:"]
```

See [`hermes-personalities.example.yaml`](hermes-personalities.example.yaml) for the full block populated with every Hermes-served handle the council uses today.

## Pattern C — handle map (the source of truth)

Both patterns above need to know "which handle maps to which justice." That's the [`handle-map.example.json`](handle-map.example.json) file at the root of `~/.council/`:

```json
{
  "@NonOtto_bot":           { "justice": "Otto",   "framework": "openclaw" },
  "@DrNonOpenClaw_bot":     { "justice": "Otter",  "framework": "openclaw" },
  "@NonRadar_bot":          { "justice": "Radar",  "framework": "hermes"   },
  "@DrNonHermesV2_bot":     { "justice": "Aviva",  "framework": "hermes"   }
}
```

The handle map is canonical. Every framework-specific routing config (the OpenClaw `agent.json`, the Hermes `personalities.yaml`) reads from this file at startup. One source of truth; no drift.

## Why the SOULs aren't all in this directory

[`per-handle/`](per-handle/) shows a few canonical examples (Otto for council, Otter for personal, Civic to disambiguate from Otto). The full set of SOULs lives at [`../souls/`](../souls/) — Bob, Otto, Nun were shipped in the queue PR; this PR extends with Otter and Civic. Wire each up via the patterns above.

## Verification

1. **Smoke test:** DM `@DrNonOpenClaw_bot` asking *"Who are you?"* — expect *"Otter, your personal assistant"*, NOT *"Otto"*.
2. **Council test:** Mention `@NonOtto_bot` in the council group — expect Otto-flavored response with palette verb (`DRAFT:` / `SENT:` etc.).
3. **No more identity-correction inbounds.** Grep your Hermes log: `grep -E 'you are not|you.re not' ~/.hermes/logs/gateway.log` — should drop to zero after both patterns are wired.

## What this directory does NOT do

- **Doesn't ship the framework wiring.** OpenClaw's agent dispatcher and Hermes's personalities loader are framework-side code. This directory ships the *config templates* both can consume; the loader work is M1 in [ROADMAP.md](../../ROADMAP.md).
- **Doesn't fix the live `~/.openclaw/SOUL.md`.** That's an on-Mac edit you make once after reviewing the templates here.
- **Doesn't touch credentials.** All identity is metadata; no API keys, no Telegram tokens. Those live in Keychain per [SECURITY.md](../../SECURITY.md).
