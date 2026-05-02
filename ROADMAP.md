# Roadmap — toward Manus-class capability at $0

The protocol stack is the IP. The implementation work that comes next is what closes the gap with Manus-class autonomous-agent systems while keeping the cost at $0/month.

## Now — shipped on this branch

The protocol stack ([docs/INDEX.md](docs/INDEX.md)) is complete:

- **The floor:** `communication-protocol.md` (the wire format, the five rules, the minimum-viable-bot).
- **The mindset:** `council-soul.md` (Musk · Bezos · Norman · Pinker · 3 Cs · Flow).
- **The bench:** `justice-roles.md` (eleven justices + noN's archive role).
- **The court:** `council-protocols.md`, `tenet-router.md`, `inter-bot-protocols.md`.
- **Production:** `production-mode.md`, `multi-task.md`.
- **Learning:** `learning-loops.md`.
- **Networking:** `transcript-fix.md`, `relay-bridge.md`.

Implementation that landed:

- `examples/council-transcript.example.py` — Lock 2 redaction in `append()`; bot_id + machine fields.
- `examples/relay/relay.py` — Telethon user-account relay bridging unpatchable bots.
- `examples/learning/reflect.py` — pin → exemplar cron.
- `examples/analytics/hourly-digest.py` — noN's hourly Obsidian digest.
- `examples/policy/policy.example.json` — capability-matrix schema.
- `infra/tailscale-acl.json` — Lock 1 ACL spec.
- `.github/workflows/lint.yml` + `scripts/lint-no-exec.sh` — Lock 5 in CI.

## Next — Q2 2026 (the Manus-parity sprint)

Five milestones, each independently shippable:

### M1 — Per-framework `policy.json` loaders

Turn the capability matrix from policy into binding code. Three frameworks (nanobot, Hermes, OpenClaw); plan tracked at [`policy-json-enforcement-layer.md`](https://github.com/agentic-ai-research/dr-non-diy-ai-council/tree/claude/upbeat-boyd-9e0242). Until this lands, the matrix in [docs/inter-bot-protocols.md](docs/inter-bot-protocols.md) is policy-only — a justice could call a forbidden tool. After it lands, she can't.

### M2 — Live deployment of the protocol stack

Drop the launchd plists onto the council Mac:
- `ai.council.relay` — the Telethon user-account relay.
- `ai.council.reflect` — the per-thread exemplar cron.
- `ai.council.hourly-digest` — noN's silent observer cron.
- `ai.council.transcript-rotate` — the daily symlink rotation already in `transcript.py`.

After M2, the council is **running** in production, not just designed.

### M3 — Public-account integration

Otto's capability matrix extends to `twitter`, `linkedin`, `youtube`. The standing-order pattern from [docs/multi-task.md](docs/multi-task.md) kicks in: every public post `BENCH:`es until graduated. This is the clearest user-visible win — Dr Non's social presence runs autonomously under his rules, not the platform's.

### M4 — DeepWork iOS app ships

LOL builds on the M5 Max, threaded through the council's `WORKFLOW` and `BUILD` modes. The contract files in `~/.council/contracts/` mediate Eve↔LOL. This proves the cross-builder collaboration grammar (`CONTRACT:` / `NEEDS-IOS:` / `NEEDS-BACKEND:`) works on a real product.

### M5 — Public reproducibility test

One external team forks the repo, follows [docs/INDEX.md](docs/INDEX.md), sets up their own council on their own Mac, and ships a pinned thread within two hours of `git clone`. This validates that the docs are sufficient — that the protocol stack can be lifted, not just admired.

## After — H2 2026 (post-parity)

Three directions where the council does things Manus doesn't:

### Multi-tenant council

Different users running their own council instances on shared protocol stack. The transcript schema, the verb palettes, the bench protocol — all reusable. A `council-template/` repo as the install-and-go starter kit.

### Skill marketplace

Palette verbs become composable. New justices ship as palettes + SOUL files + `policy.json` rows. A `Sis` justice for sister-style emotional intelligence; a `Nun` justice for vow-of-silence research; a `Rotor` justice for mechanical-engineering work. Palindrome names required.

### Federated transcripts

Councils collaborate across organizations. A research lab's council pings a partner lab's council via shared transcript over Tailscale; the receiving Tenet routes the message into its local thread graph. Cross-organization research at the speed of a JSONL append.

## Honest gaps — what this is NOT yet at parity on

Three Manus-class capabilities the council does not have today:

1. **Browser automation.** Manus drives Chromium; this council does not. The relay's user-account architecture is the closest analog — a Telethon client driving Telegram on a real account — but a full browser sandbox is M2-or-later work.
2. **Computer-use VM control.** Manus has a sandboxed virtual machine and can click pixels; this council operates through APIs and file-system writes, not through a virtual desktop. Adding it means a new justice with `computer-use` capability, an isolated VM (Lima or UTM on the M5 Max), and a strong audit trail.
3. **Fine-tuned tool-use weights.** Manus has proprietary fine-tunes; the council uses base free-tier weights with prompt-level discipline. Closing the quality gap means either (a) accepting a 5–10% coordination delta as the cost of $0/month, or (b) eventually fine-tuning a small open-weights model on the exemplar library produced by `reflect.py`. Option (b) is plausible once the library is rich enough — call it the H2 2026 stretch goal.

## Decision log

- **Eleven justices, palindrome names.** The naming rule is constitutional (see [README.md](README.md)). Adding a 12th justice requires a palindrome name and a `policy.json` row.
- **Two-Mac topology.** M3 Air = council Mac (canonical `~/.council/`), M5 Max = iOS dev (mounts shared transcript via Tailscale + SMB). Adding a third machine requires Tailscale ACL changes ([infra/tailscale-acl.json](infra/tailscale-acl.json)) and a discussion on whether the role justifies it.
- **Markdown over YAML.** All design docs are markdown. Configuration uses JSON. No YAML in this repo.
- **Stdlib-only for reference implementations.** `relay.py` uses Telethon (one external dep); everything else (`transcript.py`, `reflect.py`, `hourly-digest.py`) is stdlib-only by policy. This keeps the install path under 5 minutes for any contributor.

## What this roadmap is NOT

- **Not a release schedule.** Dates are intent, not commitment. M1–M5 may land in any order; M5 may land first if an external team picks the repo up tomorrow.
- **Not exhaustive.** Dr Non may add or drop milestones. The protocol stack is constitutional; the roadmap is a working document.
- **Not a sales pitch.** The honest-gaps section is non-negotiable. If the council ships M1–M5 and still lacks browser automation, the README must say so.
