# `policy.json` — capability matrix as code

The schema referenced by the inter-bot protocols ([docs/inter-bot-protocols.md §1](../../docs/inter-bot-protocols.md)) and the enforcement plan tracked separately. This file is the **schema reference** — concrete entries for every justice — so the loaders that come later (per-framework, in nanobot/Hermes/OpenClaw) have something to align against.

## What this file is

A single JSON document at `~/.council/policy.json` on the council Mac. Each bot's harness reads it at boot, looks up its own entry by `bot_id` (sourced from `$COUNCIL_BOT_NAME`), and registers **only** the tools listed in its entry. A tool not in the list is unreachable from that bot's process — even if the framework would otherwise expose it.

## What this file is NOT

- **Not enforcement.** Until the per-framework loaders land (see the policy-json-enforcement-layer plan tracked outside this repo), this file is documentation only — what *should* be true. Implementing the loaders is the work that turns the schema into binding rules.
- **Not the markdown matrix.** The capability matrix in [docs/inter-bot-protocols.md](../../docs/inter-bot-protocols.md) is the human-readable view; this JSON is the machine-readable view. Both should match. Eventually a small script renders one from the other.

## How to use

1. Copy this file to `~/.council/policy.json` on the council Mac.
2. Verify each bot's `bot_id` matches the `$COUNCIL_BOT_NAME` set in its launchd plist (the keys in this file's `bots` map are the canonical IDs — `tenet`, `radar`, `otto`, `hannah`, `ada`, `ana`, `civic`, `aviva`, `bob`, `pip`, `non`, `eve`, `lol`).
3. When the per-framework loaders ship, each bot's harness will refuse to start if the policy file is missing or its `bot_id` isn't found. Until then, this file informs design but doesn't gate anything.

## Constraints field

Some tools need more than a yes/no. The `constraints` block carries the qualifier:

| Constraint shape | Meaning |
|---|---|
| `"<tool>": "read-only"` | API calls are allowed only with read verbs (no POST / PUT / DELETE). |
| `"<tool>": "feature-branch-only"` | `git-push` may target any branch *except* `main` / `master` / default. |
| `"<tool>": [list of paths or commands]` | Allowlist: only the listed values are permitted (e.g., `shell-exec`, `fs-write`). |
| `"<tool>": { "max_recipients": N, ... }` | Structured constraints (e.g., email caps). |

Keep the constraint language small. If a constraint needs logic, write it as code in the bot's harness, not as config here.
