# OpenClaw — split into per-handle agents

Today `~/.openclaw/agents/` has one agent: `main`. The single `~/.openclaw/SOUL.md` ("Your name is Otto") is read by every Telegram bot account the gateway serves, including `@DrNonOpenClaw_bot` (Otter). That's why Otter answered as Otto.

The fix: one agent directory per Telegram handle, each with its own SOUL.

## Target layout

```
~/.openclaw/agents/
├── otto/
│   ├── agent.json        — { "telegramUsername": "NonOtto_bot", "channels": ["council-group"] }
│   ├── SOUL.md           — Otto's identity (council executor)
│   └── IDENTITY.md       — voice / refusals
│
├── otter/
│   ├── agent.json        — { "telegramUsername": "DrNonOpenClaw_bot", "channels": ["dm"] }
│   ├── SOUL.md           — Otter's identity (personal assistant)
│   └── IDENTITY.md
│
├── civic/
│   ├── agent.json        — { "telegramUsername": "DrNonOpenClaw2026_bot", "channels": ["council-group"] }
│   ├── SOUL.md           — Civic's identity (utility-frame justice)
│   └── IDENTITY.md
│
└── main/                 ← deprecated; remove after migration verified
```

## Migration steps

```bash
# 0. Back up the existing agent — never delete first.
mv ~/.openclaw/agents/main ~/.openclaw/agents/main.archive-$(date -u +%Y-%m-%d)

# 1. Create per-handle agents. The names match the handle map.
mkdir -p ~/.openclaw/agents/otto ~/.openclaw/agents/otter ~/.openclaw/agents/civic

# 2. Drop the per-handle SOULs from this repo into the right slots.
#    Examples in examples/identity/per-handle/ at this repo's root:
cp examples/identity/per-handle/Otto.SOUL.example.md   ~/.openclaw/agents/otto/SOUL.md
cp examples/identity/per-handle/Otter.SOUL.example.md  ~/.openclaw/agents/otter/SOUL.md
cp examples/identity/per-handle/Civic.SOUL.example.md  ~/.openclaw/agents/civic/SOUL.md

# 3. Create per-agent agent.json bindings. Each names its Telegram handle.
cat > ~/.openclaw/agents/otto/agent.json <<EOF
{
  "telegramUsername": "NonOtto_bot",
  "channels":         ["council-group"],
  "role":             "Executor",
  "framework":        "openclaw"
}
EOF

cat > ~/.openclaw/agents/otter/agent.json <<EOF
{
  "telegramUsername": "DrNonOpenClaw_bot",
  "channels":         ["dm"],
  "role":             "Personal Assistant",
  "framework":        "openclaw"
}
EOF

cat > ~/.openclaw/agents/civic/agent.json <<EOF
{
  "telegramUsername": "DrNonOpenClaw2026_bot",
  "channels":         ["council-group"],
  "role":             "Utility-frame Justice",
  "framework":        "openclaw"
}
EOF

# 4. Restart the gateway so it re-discovers the agents directory.
launchctl kickstart -k "gui/$(id -u)/ai.openclaw.gateway"
```

## Routing — the gateway side

Once the per-agent directories exist, OpenClaw's gateway reads `agent.json` files at startup and dispatches inbound Telegram messages to the agent whose `telegramUsername` matches the message's `bot_username`. Each agent's SOUL is loaded into that request's system prompt — so Otter's request only sees Otter's SOUL, never Otto's.

If the gateway version on this Mac doesn't yet support per-agent dispatch by `agent.json`, an explicit `routing.json` at the gateway root works the same way. Sketch:

```json
{
  "routing": [
    { "from_username": "NonOtto_bot",         "agent": "otto" },
    { "from_username": "DrNonOpenClaw_bot",   "agent": "otter" },
    { "from_username": "DrNonOpenClaw2026_bot","agent": "civic" }
  ],
  "fallback": "otto"
}
```

`fallback: "otto"` means "if a handle isn't in the routing table, use Otto's SOUL." Set this to `null` to fail closed — log a warning, send a one-line reply asking Dr Non to configure the handle.

## Verification

After restart, send three test messages and check each bot answers as the right justice:

```
DM @DrNonOpenClaw_bot:        "Who are you?"        → expect "Otter"
council group @NonOtto_bot:    "Who are you?"        → expect "Otto"
council group @DrNonOpenClaw2026_bot: "Who are you?"  → expect "Civic"
```

Then `grep -E 'you are not|you.re not' ~/.hermes/logs/gateway.log` to confirm no more identity-correction inbounds.

## Rollback

If anything misbehaves:

```bash
rm -rf ~/.openclaw/agents/{otto,otter,civic}
mv ~/.openclaw/agents/main.archive-* ~/.openclaw/agents/main
launchctl kickstart -k "gui/$(id -u)/ai.openclaw.gateway"
```

You're back to the pre-migration state in 30 seconds.
