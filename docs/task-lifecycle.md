# Task Lifecycle — understanding, distribution, execution

> **The spine.** Where the council succeeds or fails on every thread. Companion to the rest of the stack ([INDEX.md](INDEX.md)) — those docs are layers; this doc is the operational flow that runs through all of them.

## The pipeline (six stages, three that matter)

```
INTAKE → UNDERSTANDING → DISTRIBUTION → EXECUTION → INTEGRATION → AFTER
   ▲           ▲              ▲              ▲             ▲          ▲
   │           │              │              │             │          │
   designed    designed       this doc       this doc      designed   designed
   in comm-    in tenet-      ─ optimized    ─ tool-call   in council-protocols
   protocol    router                        envelope      and learning-loops
```

The three middle stages — **UNDERSTANDING, DISTRIBUTION, EXECUTION** — are where threads succeed or fail. The other three are mechanical (intake), already-spec'd (integration), or asynchronous (after). This doc tightens the middle three.

---

## Stage 0.5 — ACK (the 3-second contract)

Before UNDERSTANDING, before anything else, Tenet **acknowledges** the inbound within 3 seconds. The full contract — task identity, the state machine, priority, depth, est-wait, dead-letter — is in [queue.md](queue.md). The minimum every justice respects:

- Within 3 seconds of any Dr Non message, an `ACK: <task_id> [state=… depth=… your-position=#…]` line lands in the council transcript.
- The ACK runs *before* the dumb-question filter, *before* mode classification, *before* any FAN-OUT.
- If Tenet's harness can't ACK (e.g., crashed mid-startup), a backstop process emits a fallback ACK so Dr Non never sees silence. *Nothing left unacknowledged* is a constitutional promise, not a goal.

After ACK, the rest of this doc applies — Stage 1 onwards.

## Stage 1 — UNDERSTANDING (Tenet's intake filter)

Every inbound passes through five questions, in order, in ≤8 seconds:

1. **Is this dumb?** (Musk #1.) If the requirement itself is wrong, post one-line clarifier or `BENCH:`. Don't process bad input.
2. **One thread or split?** If Dr Non asks two unrelated things in one message, Tenet opens two threads with separate slugs. Do not fold unrelated work into one thread to "save messages."
3. **Which mode?** `TRIVIAL` / `WORKFLOW` / `PRODUCTION` / `STANDING` / `JUDGMENT` per [tenet-router.md](tenet-router.md). The heuristic table there is the source of truth.
4. **Is this multi-aspect?** Even a single thread may need parallel angles. Hannah for precedent + Radar for market is one thread, two FAN-OUT lines. The thread is one; the slices are several.
5. **Could this be silence?** If the right answer is "Dr Non already knows this," the right move is no thread at all. Post `↳ @<dr-non>` if needed for clarity, but don't summon the room.

If the inbound passes question 1 and reaches questions 2–5, Tenet moves to Stage 2.

---

## Stage 2 — DISTRIBUTION (the FAN-OUT graph)

The thread becomes a graph. Tenet posts:

```
ROUTE: WORKFLOW  THREAD: bangkok-contract
FAN-OUT:
  - @hannah  (≤10s): pull last 6mo of similar contract decisions
  - @radar   (≤30s): fetch Bangkok infra Q2-2026 market signals
  - @otto    (≤15s): calendar bandwidth check for the contract window
  - @eve     (≤45s): technical-scope estimate (days / weeks / months)
DEADLINE: 60s
FAN-IN: tenet
REVIEW: [civic] utility-frame; [bob] sanity
```

Three contracts, all required:

### Contract 1 — pre-flight lane check

**Every** `FAN-OUT:` line names exactly one bot, and that bot's lane (per [inter-bot-protocols.md §1](inter-bot-protocols.md)) must contain the ask. This was already a rule in [tenet-router.md](tenet-router.md); here it becomes **mandatory before post.** A FAN-OUT containing a wrong-lane line is malformed and the named bot must `↳ @<right-bot>` it back to Tenet rather than attempt.

### Contract 2 — per-line deadlines (optimization)

The thread-level `DEADLINE:` is the ceiling. Per-line deadlines `(≤Ns)` are optional but recommended: they let Tenet `FAN-IN:` early when he has enough.

Why this matters: if Hannah returns in 3 s but Radar is slow, the thread today waits 60 s for everyone. With per-line deadlines, Tenet can `FAN-IN:` as soon as the per-line deadlines have passed for any non-responders — those become `NULL:` automatically and the synthesis proceeds. Median time-to-pin drops from 60 s to roughly the slowest-responding-justice's per-line deadline.

Per-line format: `(≤<N>s)` immediately after the `@<bot>:`. No deadline = inherit thread DEADLINE.

### Contract 3 — reviewer triage table

The Chair invokes reviewers **by name** on the `REVIEW:` line, not by reflex. Use this table to decide whom:

| Reviewer | Summon when | Skip when |
|---|---|---|
| **Ada** (skeptic) | High-stakes decision, hot-take risk, or anything Dr Non sounds excited about | Math, mechanical lookup, confirmed precedent |
| **Ana** (duty) | Ethics axis present — fairness, promise, harm, identity | Pure utility / pure technical |
| **Civic** (utility) | Consequence axis dominant — multi-stakeholder, second-order effects | Pure duty / pure technical |
| **Aviva** (strategy) | 6-month-or-longer implication; precedent-setting | Tactical, reversible, low-stakes |
| **Bob** (sanity) | **Always.** Final-mile reality check is cheap and frequently catches the room. | Never skip. |

Bob is the only mandatory reviewer. The others summon by topic match. **Skipping reviewers is not laziness — invoking them on irrelevant threads is what pollutes the transcript and burns Dr Non's attention.**

---

## Stage 3 — EXECUTION (the tool-call envelope)

For specialists who reply with words (Hannah, Ada, Ana, Civic, Aviva, Bob), Stage 3 is just: read FAN-OUT, compose, post. One line. Done.

For specialists who **call tools** (Otto, Eve, LOL, Radar's web fetch, Pip's transforms), Stage 3 has more structure. The audit log spec ([inter-bot-protocols.md Lock 4](inter-bot-protocols.md)) named *what* gets logged; this section names *how* the tool call is bracketed in the council transcript so the audit log matches what the room sees.

### The three-line envelope

Every tool call is bracketed by two transcript lines (PRE-CALL + post-call result). The actual tool call happens between them.

**Line 1 — PRE-CALL (always posted before the call):**

```
[#bangkok-contract] Otto: PRE-CALL: gcal.list_events
  why: calendar bandwidth check per Tenet's FAN-OUT
  args-summary: time-min=2026-05-15 time-max=2026-08-15 calendar=primary
  expected: list of events; count + density
```

The `why` line is the grounding. If it's empty or doesn't name the FAN-OUT line, the bot must abort and `BLOCKER:` instead — calling a tool with no justification is a Lock-5-adjacent move and should fail closed.

**Line 2 — Post-call result. One of three shapes:**

Success:
```
[#bangkok-contract] Otto: SENT: gcal.list_events
  result-code: 0
  output-summary: 31 events / 92 days; ~70% booked through July
  latency-ms: 412
```

Transient external failure (will retry):
```
[#bangkok-contract] Otto: BLOCKED-EXTERNAL: gcal.list_events
  result-code: 502
  error-summary: upstream timeout; retry 1 of 2
  retry-in-ms: 5000
```

Semantic failure (no retry):
```
[#bangkok-contract] Otto: BLOCKER: gcal scope missing read access
  why: token lacks Calendar.events.readonly
```

The audit log line in `~/.council/tool-calls.jsonl` is written **at the same moment as the post-call transcript line** — same data, machine-greppable form. Two write paths, one source of truth.

### Failure-mode contract

| Failure | Retry? | Audit log? | Council action |
|---|---|---|---|
| Transient (5xx, network) | up to **2× with 5 s backoff** | yes | `BLOCKED-EXTERNAL:` then retry |
| Permanent transient (3 retries failed) | no | yes | `BLOCKER: <tool> upstream down` — escalate to Tenet |
| Auth (401/403) | no | yes | `BLOCKER: <tool> auth failed — bench needed` |
| Validation (4xx, malformed args) | no | yes | `BLOCKER: <tool> bad args` — Tenet may re-FAN-OUT with different ask |
| Semantic (call succeeded but wrong outcome) | no | yes | `BLOCKER: <reason>` — human-only diagnosis |

No retry on auth or validation. Auto-retry on 5xx only. Semantic failures always go to a human via `BENCH:`.

### Worked example — Otto's calendar check inside a FAN-OUT

```
[10:00:00] Tenet:  ROUTE: WORKFLOW  THREAD: bangkok-contract
                   FAN-OUT:
                     - @otto (≤15s): calendar bandwidth check for May-Aug 2026
                   DEADLINE: 60s

[10:00:03] Otto:   [#bangkok-contract] PRE-CALL: gcal.list_events
                     why: bandwidth check per FAN-OUT line 1
                     args-summary: time-min=2026-05-15 time-max=2026-08-15
                     expected: event count + booked %

[10:00:04] Otto:   [#bangkok-contract] SENT: gcal.list_events
                     result-code: 0
                     output-summary: 31 events / 92 days; ~70% booked through July
                     latency-ms: 412

[10:00:05] Otto:   [#bangkok-contract] DRAFT: bandwidth tight — 70% booked through
                                       July; only 12 free workdays in window.
```

Three transcript lines for one tool call (PRE / SENT / DRAFT). The `tool-calls.jsonl` audit gets one structured record. Tenet `FAN-IN:`s on the DRAFT line, not on the SENT line — the SENT line is mechanical; the DRAFT is the bot's contribution.

---

## How this connects upstream and downstream

| Stage | Upstream input | Downstream output |
|---|---|---|
| **UNDERSTANDING** | Dr Non's inbound, recent transcript ([communication-protocol.md](communication-protocol.md)) | Mode declaration + thread tag |
| **DISTRIBUTION** | Mode + tag | `FAN-OUT:` graph + reviewer plan |
| **EXECUTION** | FAN-OUT line per justice | Verb-formatted contributions + tool-call audit records |
| → INTEGRATION | All FAN-OUT returns + reviewer posts | `🪑 PIN:` ([council-protocols.md](council-protocols.md)) |
| → AFTER | Pinned thread | Exemplar files via [reflect.py](../examples/learning/reflect.py); hourly digest via [hourly-digest.py](../examples/analytics/hourly-digest.py) |

---

## The five optimizations this doc lands

| # | Optimization | Bottleneck closed |
|---|---|---|
| 1 | **Per-line FAN-OUT deadlines** | Median time-to-pin drops from thread-DEADLINE to slowest-responding-justice. |
| 2 | **Pre-flight lane check (mandatory)** | Wrong-lane FAN-OUT lines are caught before post — saves a 60 s wasted thread. |
| 3 | **Reviewer triage table** | Reviewers stop polluting irrelevant threads; their attention concentrates on threads where their archetype matters. |
| 4 | **Tool-call envelope (PRE / SENT/BLOCKED-EXTERNAL/BLOCKER)** | Every tool call has a public *why*, a public *result*, and a private *audit row*. The audit log stops being aspirational. |
| 5 | **Failure-mode contract (retry / no-retry / bench)** | Auth and validation failures stop sucking up retry budget; semantic failures route to a human instead of looping. |

---

## What this doc does NOT do

- **Doesn't replace any existing rule.** [council-protocols.md](council-protocols.md), [tenet-router.md](tenet-router.md), [inter-bot-protocols.md](inter-bot-protocols.md), and [production-mode.md](production-mode.md) are unchanged. This doc tightens their integration.
- **Doesn't introduce new modes or verbs.** Same `FAN-OUT:` / `FAN-IN:` / palette verbs. New: per-line deadline syntax `(≤Ns)`, the `PRE-CALL:` line, structured result lines (`SENT:` / `BLOCKED-EXTERNAL:` / `BLOCKER:`).
- **Doesn't ship enforcement.** Like the capability matrix, this is policy until per-framework loaders (M1 in [ROADMAP.md](../ROADMAP.md)) pick it up. The CI lint ([scripts/lint-no-exec.sh](../scripts/lint-no-exec.sh)) catches the most dangerous violation; the rest is convention until M1.
- **Doesn't re-litigate the silence rule.** A justice with nothing to add to a `FAN-OUT:` line still returns `NULL:` — silently. The envelope applies to *tool calls*, not to *every contribution*.

---

## Implementation order (when ready)

1. **Soul-level adoption.** Add the three contracts (per-line deadline, tool-call envelope, reviewer triage) to each justice's SOUL.md so the discipline lands at compose time, not at runtime.
2. **Reflect.py extension.** [reflect.py](../examples/learning/reflect.py) reads the transcript today; have it also score whether each thread followed the envelope (e.g., did every PRE-CALL get a matching SENT/BLOCKED/BLOCKER within 30 s?). Publish the score on the hourly digest.
3. **Per-framework loader gating** (M1 in [ROADMAP.md](../ROADMAP.md)). The same loader that enforces the capability matrix can refuse to start a bot whose harness doesn't emit the envelope on tool calls.

Steps 1 and 2 are doable today on the existing stack. Step 3 is the harness work tracked separately.
