# Queue — multi-tasking is the council's main feature

> **The promise:** *Nothing unacknowledged.* Every inbound from Dr Non gets an `ACK:` line in the council transcript within **3 seconds**, before any other action. The council is a queuing master before it is anything else. Companion to [communication-protocol.md](communication-protocol.md), [tenet-router.md](tenet-router.md), [multi-task.md](multi-task.md) (which now covers the per-thread tagging and standing-order *subsets* of this queue).

## Why this is the headline feature

Manus-class systems brag about "doing many things at once." The council's version of that promise is stronger: not just *doing* — *acknowledging*. A queue without ACKs is a black box. A queue with ACKs is a contract. Dr Non always knows: *received*, *queued at position N*, *in flight*, *done*, *failed*. No inbound disappears. No status is implicit.

## Sources of design (what we borrowed)

| System | What we took |
|---|---|
| **Celery (Python)** | Explicit task state machine — named states, transitions are the API. |
| **Sidekiq / BullMQ** | *Visibility timeout* / *lease*: a worker claims a task; if it doesn't finish within T, the task becomes claimable again. Crashed-bot recovery. |
| **Apache Kafka** | Append-only log + consumer offset. The queue's `index.jsonl` is exactly this — Kafka-shape over the file system. |
| **Postgres `FOR UPDATE SKIP LOCKED`** | Atomic claim. `os.rename()` between `pending/` and `claimed/<bot_id>/` is the file-system equivalent. |
| **Priority queues (Celery / BullMQ)** | `urgent | high | normal | low`; urgent preempts; the rest are FIFO within their tier. |

What every one of them gets right and we steal: **ack-then-process**, **idempotency**, **dead-letter queue**.

## Task identity

Every task carries an ID:

```
<slug>-<epoch>
e.g.  bangkok-contract-1730476212
```

The slug is short, lowercase, hyphen-separated. The epoch is the Unix timestamp at `RECEIVED`. The thread tag derives directly: `[#bangkok-contract]`. Slugs without epochs are reserved for standing orders (which never expire — their identity is the slug alone).

Idempotency: `enqueue()` hashes the payload. If the same payload is enqueued twice, the second call returns the existing `task_id` — no double-processing.

## The state machine

```
RECEIVED → QUEUED → CLAIMED → IN-FLIGHT → DONE
                       │           │
                       │           └─→ BLOCKED-ON-BENCH ─→ IN-FLIGHT (resume)
                       │           └─→ FAILED → (retry?) → QUEUED  |  → dead/
                       └─→ (visibility timeout) → QUEUED  (reclaim)

                                                     REVOKED  (Dr Non / Tenet kill)
```

Every transition is one transcript line. The same line goes to `~/.council/queue/index.jsonl` in machine-greppable form — two paths, one source of truth, same as the Lock 4 audit log pattern.

## Tenet's first move on every inbound

Within **3 seconds** of any message from Dr Non, Tenet performs three steps in this order:

1. **Classify NEW vs CONTINUATION.** Rule: if the message text starts with a `[#<slug>]` thread tag *or* explicitly references a recent active task by name, it's a CONTINUATION. Otherwise, NEW.
2. **ACK.** Post the acknowledgement in council transcript:
   ```
   ACK: <task_id> [state=QUEUED, depth=12, your-position=#3, est-wait=8m, priority=normal]
   ```
   For a CONTINUATION:
   ```
   ACK: <task_id> [state=IN-FLIGHT, continuation, current-stage=fan-in]
   ```
3. **Decide:** *finish current first* or *deploy sub-agents in parallel*. Default: parallel up to the concurrency limit (3); above that, queue.

Nothing else happens before the ACK. If Tenet's harness is unable to ACK within 3 s, the inbound goes to a backstop: a stdlib script (`enqueue.py` in the watchdog directory, future work) writes a fallback `ACK:` so the inbound is still acknowledged. The user must never see silence.

## Priority tiers

| Tier | Behaviour |
|---|---|
| `urgent` | Preempts the current in-flight task at the next clean breakpoint. The preempted task returns to position 0 of its tier with state preserved. |
| `high` | Jumps the queue ahead of `normal` and `low`. FIFO within `high`. |
| `normal` | The default. FIFO. |
| `low` | Background work; only runs when no `normal+` is queued. |

Default is `normal`. Dr Non can override on the inbound: `[priority: urgent]` anywhere in the message.

## Concurrency

- **In-flight cap:** 3 tasks at once by default. Configurable in `~/.council/queue/config.json`.
- **Per-bot cap:** each bot's harness queues its own work; a bot is at most one "active station" per task per [production-mode.md](production-mode.md).
- **Reviewer parallelism:** reviewers (Bob, Ada, Ana, Civic, Aviva) are not counted against in-flight cap — they're per-task overhead, not parallel tasks.

When the in-flight cap is hit, new tasks land at `QUEUED` and wait.

## The ACK ledger

`~/.council/queue/index.jsonl` is append-only, one line per state transition:

```jsonl
{"ts":"2026-05-02T14:30:01+07:00","task_id":"bangkok-contract-1730476212","from":"received","to":"received","priority":"normal","actor":"Dr Non"}
{"ts":"2026-05-02T14:30:02+07:00","task_id":"bangkok-contract-1730476212","from":"received","to":"queued","priority":"normal","actor":"Tenet","position":3,"depth":12}
{"ts":"2026-05-02T14:32:18+07:00","task_id":"bangkok-contract-1730476212","from":"queued","to":"claimed","actor":"Tenet","worker":"tenet-router"}
{"ts":"2026-05-02T14:32:19+07:00","task_id":"bangkok-contract-1730476212","from":"claimed","to":"in-flight","actor":"Tenet"}
{"ts":"2026-05-02T14:33:42+07:00","task_id":"bangkok-contract-1730476212","from":"in-flight","to":"done","actor":"Tenet","pin_ref":"transcript-2026-05-02.jsonl#l4421"}
```

Anyone with read access can `tail -f` this file and watch the queue work. The hourly digest reads it for the analytics rollup.

## Backpressure

When the queue depth crosses 10, Tenet's ACK changes shape:

```
ACK: <task_id> [QUEUED depth=12 est-wait=8m your-position=#3]
HEADS-UP: queue depth above threshold; consider letting current threads finish before opening more.
```

When depth crosses 25, Tenet starts refusing low-priority work explicitly:

```
ACK: <task_id> [REJECTED queue-full]
RECOMMEND: re-send when depth drops, or mark `[priority: high]`.
```

Dr Non always sees the back-pressure — the queue is never silently full.

## Dead-letter queue

A task that fails its retry budget (default 3 retries with exponential backoff `30s · 2m · 5m`) moves to:

```
~/.council/queue/dead/<task_id>.json
```

Each file contains: payload, every state transition, every retry attempt, the final error. Hourly digest surfaces new DLQ entries:

```markdown
## Dead-letter queue (this hour)
- `bangkok-contract-…` — failed 3× on Otto's gmail.send (last error: 401)
```

Dr Non reviews; if the task is still wanted, he `git mv`s it back to `pending/` (or runs `python -m queue revive <task_id>`).

## Crashed-bot recovery (visibility timeout)

A `CLAIMED` task without an `IN-FLIGHT` heartbeat within **30 seconds** is reclaimed: moved back to `pending/`, available for any worker. The bot that claimed it might still come back later — that's fine; the second worker's claim is now authoritative, and the first worker's `start()` will fail because the file moved.

This means a crashed Otto can't strand a task. The next live worker picks it up.

## Worked example — three concurrent inbounds, one preemption, one failure

```
[14:30:00] Dr Non: should I take the bangkok contract?
[14:30:02] Tenet:  ACK: bangkok-contract-1730476212 [state=QUEUED depth=1 your-position=#1 priority=normal]
                   ROUTE: WORKFLOW  THREAD: bangkok-contract
                   FAN-OUT: ...

[14:30:30] Dr Non: also can you draft the friday weekly to the depa team?  [priority: high]
[14:30:32] Tenet:  ACK: depa-friday-1730476230 [state=IN-FLIGHT priority=high]
                   ROUTE: WORKFLOW  THREAD: depa-friday
                   ↳ @otto: draft body, BENCH for approval

[14:31:15] Dr Non: emergency — flight to BKK got cancelled, need to rebook  [priority: urgent]
[14:31:17] Tenet:  ACK: rebook-flight-1730476275 [state=IN-FLIGHT priority=urgent PREEMPTING]
                   PREEMPT: bangkok-contract returning to position 0 (state preserved)
                   ↳ @otto: rebook BKK flight
                   ↳ @radar: pull alternative routings

[14:32:05] Otto:   [#rebook-flight] BLOCKER: kayak.search returned 401 (NIM key revoked?). Retry 1/3.
[14:33:35] Otto:   [#rebook-flight] BLOCKER: retry 2/3 also 401.
[14:36:05] Otto:   [#rebook-flight] BLOCKER: retry 3/3 also 401. Routing to DLQ.
[14:36:06] Tenet:  FAIL: rebook-flight-1730476275 [state=DEAD reason="401 after 3 retries"]
                   BENCH: rebook task in DLQ — Otto's NIM key likely needs rotation. APPROVAL?
                   RESUME: bangkok-contract-1730476212 [state=IN-FLIGHT]
```

Three inbounds, one priority preemption, one failure cleanly captured in DLQ, and the urgent task didn't lose any state when it was bumped. Dr Non saw an ACK on every message within 2 seconds.

## What this doc does NOT do

- **No broker.** No Redis, no RabbitMQ, no NATS, no Kafka actual. File-based, single-Mac.
- **No distributed locking.** Single owner of `~/.council/queue/`. Cross-Mac queues are M2 in [ROADMAP.md](../ROADMAP.md).
- **No saga / compensation patterns.** Multi-step orchestration uses existing `FAN-OUT:` / `FAN-IN:`; this queue is for top-level tasks, not nested workflows.
- **No replacement of existing verbs.** `ACK:`, `QUEUED:`, `IN-FLIGHT:`, `DONE:`, `FAILED:`, `REVOKED:` are *additive* to every justice's palette; nothing existing changes.
- **No enforcement at the harness level.** Like the rest of the policy stack, the loaders pick this up in [ROADMAP.md](../ROADMAP.md) M1. Until then, the contract is convention; the reference [examples/queue/queue.py](../examples/queue/queue.py) is the runnable proof.
