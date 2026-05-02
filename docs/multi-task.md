# Multi-task — concurrent threads, task termination, standing orders, public accounts

> Companion to [council-protocols.md](council-protocols.md), [tenet-router.md](tenet-router.md), [justice-roles.md](justice-roles.md). The council runs N threads in parallel. Quick answers terminate fast. Long builds run until shipped. Standing orders run forever. Public posting always passes through the bench.

## Concurrent threads

One Telegram group. N threads in flight at any moment.

Each thread carries a short slug: `deepwork`, `triage`, `bangkok-contract`, `x-monitor`. Tenet declares it when he opens:

```
MODE: WORKFLOW  THREAD: bangkok-contract
FAN-OUT:
  - @hannah: pull last 6mo of similar contract decisions
  - @radar:  fetch market signals for Bangkok infra Q2 2026
```

Every justice's reply on that thread prefixes `[#<thread>]`:

```
[#bangkok-contract] PRECEDENT: 4 similar contracts in last 6mo, 3/4 NPV-positive at 90d.
```

The JSONL transcript schema is unchanged. Thread tags live in the message text — backward-compatible. Justices filter by tag to focus; everyone *sees* every thread, but the silence rules still apply: if you have nothing to add to thread X, you don't post on thread X, even when your station is active on thread Y.

## Task classes — how each one terminates

Four classes, different termination rules. Tenet picks at routing time.

| Class | Mode | Terminates when |
|---|---|---|
| **Quick** | `TRIVIAL` / direct address | One verb back — often `ANSWER:`. Auto-closes 60 s without follow-up. Example: *5 + 2 = 7*. |
| **Deliberation** | `WORKFLOW` / `JUDGMENT` | Tenet pins when explication has diminishing returns. **Mandatory pin** if no new information appears in two consecutive contributions. |
| **Production** | `PRODUCTION` / `BUILD` | Builder posts `STATUS: shipped`; Chair pins. |
| **Standing order** | `STANDING-ORDER` | Never. Runs until Dr Non or the Chair posts `END-ORDER:`. |

The **mandatory-pin** rule prevents the council's most common failure: bots elaborating past usefulness. If two contributions in a row add nothing, the Chair pins — even if not every justice has spoken. Silence is a valid finish.

For quick answers: the simplest possible reply. `5 + 2 = 7` is one line. No deliberation, no PIN ceremony, no committee.

## Standing orders — continuous work

Some work is not a thread; it is a job. Examples:

- Monitor LinkedIn for mentions of Dr Non; post a daily digest at 8am.
- Respond to YouTube comments within 4 hours.
- Post Twitter daily at 9am, drawn from the vault's *Today I Learned* file.
- Watch Bangkok smart-city RSS feeds; flag anything relevant to current contracts.

These are **standing orders.** Declared once. Run continuously.

### Declaring an order

Tenet posts at thread open:

```
MODE: STANDING-ORDER  ORDER-ID: x-monitor
OWNER: @otto
CADENCE: hourly
TERMS:
  - Watch X mentions of "@DrNonArkara" or "Bangkok smart city"
  - On positive engagement: BENCH for reply approval
  - On negative engagement: BENCH immediately, do not engage
APPROVAL: required-each
```

| Field | Values |
|---|---|
| `OWNER` | The justice responsible for executing the order. |
| `CADENCE` | `hourly` / `daily` / `weekly` / `on-mention` / `on-event-X`. |
| `TERMS` | One-line behavioral rules; what triggers what response. |
| `APPROVAL` | Bench gate level — `required-each` / `required-pattern` / `not-required`. |

### Standing-order palette

| Verb | Posted by | Meaning |
|---|---|---|
| `CHECKPOINT: <state>` | Owner | Posted on every cadence trigger. *"Order is alive; recent state is X."* |
| `STAND-DOWN: <reason>` | Owner or Tenet | Pause the order — no further actions until RESUME. |
| `RESUME:` | Tenet (after Dr Non confirms) | Resume a paused order. |
| `END-ORDER: <reason>` | Tenet (after Dr Non confirms) | Terminate. The order ceases. |
| `BENCH:` | Owner | Approval needed before the next action (per `APPROVAL`). |

### Approval levels

| Level | Use when | Behavior |
|---|---|---|
| `required-each` | Public posting · financial action · account creation | Every action BENCHes individually. |
| `required-pattern` | After ~10 approved actions, the order graduates: only outliers BENCH. | Positive replies auto-send; negative ones BENCH. |
| `not-required` | Internal-only, low-risk. | Vault tagging; internal calendar events. |

**Default is `required-each`.** A standing order graduates only when Dr Non DMs `graduate <order-id> required-pattern`. The conservative default is the rule.

## Public-facing accounts

Distinct from email drafts and calendar entries. Accounts that **broadcast** on Dr Non's behalf — Twitter/X, LinkedIn pages, YouTube channels, blog posts — carry reputational stakes internal tools do not.

Four rules:

1. **Otto owns them.** Public posting extends Otto's executor role on the OpenClaw harness. The capability matrix in [inter-bot-protocols.md §1](inter-bot-protocols.md) should add columns for `twitter`, `linkedin`, `youtube` to Otto's row in a follow-up commit.
2. **Default approval is `required-each`.** Every public post passes through BENCH before send. No exceptions until Dr Non graduates a specific account/order.
3. **The bench message includes destination, visibility, and sentiment.** Dr Non sees:
   ```
   [BENCH] Otto on linkedin (public, professional, neutral-positive):
     "<draft, 280 chars>"
     APPROVAL? (yes / edit / no)
   ```
   A bench message lacking destination, visibility, or sentiment is not approvable. Otto must include all three or the bench is malformed.
4. **Per-account credentials in per-bot keychain (Lock 3).** No shared creds across accounts. If Twitter credentials leak, LinkedIn is unaffected. Otto reads each account's secrets through `security find-generic-password -a $USER -s council-otto-twitter` — one keychain item per account.

### Cold-start a new account

User: *"Build me an X account."*

1. Otto creates the account → BENCHes for username choice.
2. Otto sets up profile → BENCHes for bio.
3. Otto declares standing orders (monitor / post / engage) → BENCHes for `TERMS`.
4. Tenet pins the setup.
5. Every public post BENCHes until Dr Non graduates the order.

Five bench gates before the order runs autonomously. After ~10 approved posts establish a pattern, Dr Non can graduate; outliers continue to bench.

## Cross-thread coordination

- A justice working on `[#deepwork]` does not accidentally answer a question on `[#triage]` — she filters by tag.
- Otto can own multiple standing orders simultaneously; they are independent `CADENCE` schedules. No collision.
- Ada posts `BIAS:` on `[#bangkok-contract]` while Hannah posts `PRECEDENT:` on `[#deepwork]` — different threads, both run in parallel, no collision.
- The transcript is one file. Threads are virtual, separated by tag. Single source of truth preserved.

## Concurrency safety

- POSIX `O_APPEND` atomicity guarantees safe concurrent writes for sub-`PIPE_BUF` lines (already documented in [inter-bot-protocols.md §4](inter-bot-protocols.md)).
- A justice's harness is typically single-threaded; her threads queue per-bot. This is fine — sequencing is sub-second per turn.
- Reading: append-only file = consistent snapshots for readers. No locking needed.

## Worked example — Dr Non runs three threads at once

```
[09:00] Dr Non:  what's 5 + 2?
[09:00] Tenet:   ROUTE: TRIVIAL  THREAD: math-quick  ↳ @bob
[09:00] Bob:     [#math-quick] ANSWER: 7.
                 (auto-closes at 09:01)

[09:00] Dr Non:  Eve, ship the auth refactor today.
[09:00] Tenet:   MODE: BUILD  THREAD: deepwork-auth  ↳ @eve
[09:02] Eve:     [#deepwork-auth] STATUS: branch up; 14/14 tests green.
[09:30] Eve:     [#deepwork-auth] STATUS: shipped to staging.
[09:31] Tenet:   [#deepwork-auth] 🪑 PIN: shipped.

[09:00] Dr Non:  start watching X for "@DrNonArkara".
[09:00] Tenet:   MODE: STANDING-ORDER  ORDER-ID: x-monitor  OWNER: @otto
                 CADENCE: hourly  APPROVAL: required-each
                 TERMS: BENCH every reply draft.
[09:01] Otto:    [#x-monitor] CHECKPOINT: 0 mentions in last hour. Watching.
[10:00] Otto:    [#x-monitor] CHECKPOINT: 2 mentions, both positive.
[10:00] Otto:    [#x-monitor] BENCH: draft reply to @user123 (public, neutral-positive): "<draft>". APPROVAL?
```

Three threads. Three different termination rules. One transcript. Each justice posts on her active thread, ignores the others.

## What this doc does NOT do

- **Does not introduce a new justice.** Otto extends to public accounts. If Otto becomes overloaded, the right move is a new palindrome-named justice — Dr Non's call, deferred.
- **Does not change the JSONL schema.** Thread tagging is in message text, not in fields, for backward compatibility with the existing reference module.
- **Does not relax BENCH for public posts.** Default `required-each`. Graduate explicitly via DM.
- **Does not weaken silence rules.** Multi-thread does not mean every justice posts on every thread — opposite. Filter by tag, post only when your station is active and you have something to add.
