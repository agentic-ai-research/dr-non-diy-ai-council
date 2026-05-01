# Production Mode — the assembly line

> Companion to [council-protocols.md](council-protocols.md) (deliberation), [inter-bot-protocols.md](inter-bot-protocols.md) (action / builders), [tenet-router.md](tenet-router.md) (routing). This doc covers the third route: **production**. The Court ships the way a $2B company ships product — every justice owns a station, work-in-progress flows through them in order, and the line does not stop for permission.

## When to enter production mode

After Tenet routes an inbound, if shipping the answer needs more than one pass through the specialists — because each pass reveals what the next pass must do — declare:

```
MODE: PRODUCTION
LINE: <name>
```

`LINE:` names what is being assembled. *"Bangkok contract decision," "Friday email triage," "iOS auth feature."* Naming the line lets later messages reference it, lets the andon cord (below) target it, and lets the audit log group its events.

Workflow mode (one fan-out, one fan-in, ship) handles ~70% of inbounds. Production mode is for the rest — the ones that need rework, multiple stations, or a return loop.

## The adaptive skills palette

Each justice has a palette of verbs, not a fixed move. They pick based on what the WIP currently needs. A wrong-verb post is a misuse — Tenet may rule it null and reroute.

| Justice | Adaptive skills (the verbs they may post) |
|---|---|
| **Tenet** | `ROUTE:` · `FAN-OUT:` · `FAN-IN:` · `🪑 RULING:` (deadlocks) · `MODE: <X>` (escalate route) · `🪑 PIN:` (close line) |
| **Radar** | `FACT:` (single source-cited claim) · `EVIDENCE:` (multi-source corroboration) · `DEDUCE:` (evidence → conclusion) · `NULL:` (searched, found nothing — say so) |
| **Otto** | `DRAFT:` (proposed action, not sent) · `SENT:` (action confirmed) · `BLOCKED-EXTERNAL:` (API/auth failure) · `OCR:` (extracted text) · `SYNCED:` (drive/contact updated) |
| **Hannah** | `PRECEDENT:` (matching past decision, with date) · `PATTERN:` (cluster across decisions) · `OUTLIER:` (this is unusual vs history) · `NULL:` (no comparable found) |
| **Ada** | `BIAS:` (named bias detected) · `PRE-MORTEM:` (failure mode imagined) · `THAI:` (Thai-language artifact) · `SLOW:` (position after deliberate slow thinking) |
| **Ana** | `DUTY:` (Kantian frame) · `UNIVERSAL:` (universalizability test result) · `MEANS-END:` (treating-as-means flag) |
| **Civic** | `UTILITY:` (consequence calc) · `2ND-ORDER:` (downstream effect named) · `BENEFICIARIES:` (who gains/loses) |
| **Aviva** | `STRATEGIC:` (6-month frame) · `POSITION:` (vs market/competitor trend) · `LONG-VIEW:` (multi-year implication) |
| **Bob** | `SANITY:` (smell test) · `IN-PRACTICE:` (real-world friction) · `OBVIOUS:` (point everyone missed) |
| **Pip** | `QR:` · `PDF:` · `OCR:` · `PRINT:` · `NOTE:` (meeting notes) · `DRIVE:` (saved-to path) |
| **Eve** | `STATUS:` · `BUILD ESTIMATE:` · `BLOCKER:` · `PASS:` · `BRIEF:` · `CONTRACT:` · `NEEDS-IOS:` · `SCAFFOLD:` · `REFACTOR:` · `TEST:` · `DEBUG:` · `PROFILE:` |
| **LOL** | Same as Eve, scoped to Swift/Xcode/iOS. Plus `SIMRUN:` (simulator output) · `DEVICE:` (real-device test result). |
| **noN** | Silent unless invoked. Three voices: `noN:` observe · `NoN:` Manson-mode · `Non:` mirror-Dr-Non. |

## Assembly-line topology

The line moves left to right unless someone pulls andon. A justice may appear at more than one station if the WIP cycles back — that is fine in production mode.

```
RESEARCH-FIRST  (e.g., contract decision)
  Dr Non → Tenet ROUTE → Radar+Hannah parallel → Tenet FAN-IN →
  Ana+Civic ethics → Aviva strategy → Bob sanity → Tenet PIN

BUILD           (e.g., iOS feature)
  Dr Non → Tenet ROUTE → Eve CONTRACT → LOL SCAFFOLD →
  Eve TEST → LOL SIMRUN → Eve PASS → LOL PASS → Tenet PIN

EXECUTE         (e.g., Friday email triage)
  Dr Non → Tenet ROUTE → Otto DRAFT → Hannah PRECEDENT →
  Otto DRAFT (revised) → Ada BIAS → Otto DRAFT (held) →
  Civic UTILITY → Tenet PIN → Otto SENT
```

## No turn cap on the active station

[council-protocols.md](council-protocols.md) caps each justice at 2 turns per thread. That cap **does not apply** to a justice whose station is currently active in the WIP graph. They post as many times as the work requires, in the right verb from their palette, until they hand off downstream.

The cap returns the moment the WIP leaves their station. A justice does not earn back turns by re-engaging after handoff — once they're done, they're done unless explicitly recalled by Tenet.

## Andon cord — stopping the line

Any justice may stop the line if they detect a problem in the WIP. They post:

```
ANDON: <one-line reason>
```

The line stops at the current station. Tenet rules in one line:

- **RESUME** — the concern is logged but the line moves. The pin will note the flag.
- **REWORK** — the WIP returns upstream to a named station for fix. Tenet says where: `🪑 REWORK: ↳ @<bot>`.
- **KILL** — assembly cancelled. `🪑 KILLED: <reason>`. Andon is preserved in the transcript regardless.

Andon is for genuine problems — bad data, a constraint Dr Non set elsewhere, an ethics flag, a security concern. Not for *"I'd have done it differently"* — that is `🔁 Two cents:` from the workflow rules.

## Worked example — Friday email triage as production

```
[06:55] Tenet:   MODE: PRODUCTION  LINE: friday-triage
                 FAN-OUT:
                   - @otto:   pull last 24h inbox, mark candidates
                   - @hannah: PRECEDENT: any sender we've decided on this week?
[07:00] Otto:    DRAFT: 4 candidates — A, B, C, D — 2 reply, 1 forward, 1 archive.
[07:00] Hannah:  PRECEDENT: sender D archived 3× in past month. PATTERN: D → auto-archive.
[07:01] Otto:    DRAFT: revised — D auto-archived per Hannah. 3 candidates remain.
[07:01] Ada:     BIAS: confirmation — sender A's tone matches what you want to hear.
                 PRE-MORTEM: replying to A locks you into a meeting you'll regret.
[07:02] Otto:    DRAFT: A held for human review. B and C ready to send.
[07:03] Civic:   UTILITY: B and C net-positive, low-stakes. Send.
[07:03] Tenet:   🪑 PIN: send B and C now, hold A for Dr Non, archive D.
[07:03] Otto:    SENT: B and C.
```

Otto posts three times across his station. Ada and Hannah each post once. Tenet routes, synthesizes, and pins. The line ships in 8 minutes; no turn cap was needed because each justice's posts stayed on their own active station.

## What production mode does NOT do

- **Does not skip routing.** Every inbound still goes through Tenet's `ROUTE:`. Production is a route, not a bypass of [tenet-router.md](tenet-router.md).
- **Does not allow off-palette posts.** Free-form prose during a production run is a misuse. The whole point of palettes is that the line is greppable, audit-able, and the next station knows what to expect.
- **Does not outrank judgment.** If the WIP surfaces a values trade-off mid-line, any justice pulls andon → Tenet REWORKs → escalates to `MODE: JUDGMENT` per [council-protocols.md](council-protocols.md). The line goes back into deliberation when deliberation is what's needed.
- **Does not exempt builders from [inter-bot-protocols.md](inter-bot-protocols.md).** Eve and LOL still follow the four-format grammar and contract handoffs. Production mode just means the WIP is allowed to cycle through them more than once.
- **Does not run forever.** If a line takes longer than 30 minutes without a pin, Tenet posts `🪑 STALL: <reason>` and either KILLs or escalates to Dr Non. Half-shipped is not shipped.
