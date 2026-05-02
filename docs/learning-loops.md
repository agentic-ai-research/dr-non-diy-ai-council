# Learning Loops — how each justice gets better

> Companion to [council-protocols.md](council-protocols.md), [inter-bot-protocols.md](inter-bot-protocols.md), [production-mode.md](production-mode.md), [tenet-router.md](tenet-router.md). Those docs say what each justice **does**. This doc says how each justice **improves** at doing it — over time, without retraining a single weight.

## The honest constraint

The justices run on free-tier inference (NVIDIA NIM, ThaiLLM) and local Apple Silicon (Eve, LOL). At $0/month, we do not fine-tune. Learning here is **in-context** — prompt-level, retrieval-augmented, exemplar-driven. The reward signal is the Chair's pin. The training data is the transcript.

| Aspect | What we CAN do | What we CANNOT do (without paid compute) |
|---|---|---|
| **Unsupervised** | Mine transcript for clusters, drift, anomalies. Hannah's job, generalised. | Train a foundation model. |
| **Reinforcement** | Outcome-based scoring → exemplar retrieval as few-shot at compose time. | RLHF / PPO on weights. |
| **Online updates** | Per-thread reflection job appends to a per-bot exemplar library. | Real-time gradient updates. |

The compromise is rich enough: each justice's library grows from her own contributions, scored by outcomes; retrieval surfaces the right exemplar at the right moment; the model itself stays frozen.

## The three loops

```
Per-turn (every contribution)         Per-thread (after pin)            Per-week (drift)
──────────────────────────            ──────────────────────             ─────────────────
1. Read recent transcript             1. Parse pin → score contribs     1. Aggregate verb usage
2. Retrieve top-3 exemplars            2. Append to exemplars/<bot>/      2. Compare vs 4-wk baseline
3. Compose draft                       3. Rebuild retrieval index         3. Flag drift > 2σ
4. Self-check (palette/lane/silence)
5. Post
```

Each loop has a different cost and cadence. The per-turn loop runs in-process, ~50ms. The per-thread loop runs after the Chair pins, ~5s. The per-week loop runs cron-scheduled, ~1 min.

## Goal 1 — Airtight prompt discipline

Every justice prepends a self-check to her composer:

```
Before posting, verify:
1. Does my message open with a verb from my palette? (See production-mode.md.)
2. Am I inside my lane on the capability matrix? (See inter-bot-protocols.md.)
3. Have I already posted on this thread? If yes, is my station still active?
4. Has a recent message already made my point? If yes, stay silent.

If any check fails, do not post.
```

One extra reasoning step per turn. Catches the three most common drift modes: off-palette posts, lane crossing, and redundancy.

## Goal 2 — Critical thinking that moves the project

The Chair's pin is the reward. A contribution cited in `🪑 PIN:` is reinforced (archived to `exemplars/<bot>/good/`); one ruled against or ignored is downweighted (`exemplars/<bot>/bad/`); one neither cited nor ruled against is ambiguous (`exemplars/<bot>/mixed/`).

Per-bot reward signals — what counts as "good" for each justice:

| Justice | Positive | Negative |
|---|---|---|
| **Tenet** | Route picked once and held. PIN closes thread cleanly. | Mid-flight ROUTE escalation. STALL. PIN overturned by Dr Non. |
| **Radar** | FACT / EVIDENCE cited in PIN. Source not disputed. | NULL when an answer existed. Disputed citation. |
| **Otto** | DRAFT accepted on first revision. SENT not rolled back. | DRAFT revised 3+ times. Rolled-back action. BLOCKED-EXTERNAL repeated. |
| **Hannah** | PRECEDENT cited in PIN. PATTERN validated by outcome. | OUTLIER call that turned out unremarkable. Missed comparable. |
| **Ada** | BIAS acknowledged in PIN. PRE-MORTEM matched what actually went wrong. | BIAS dismissed by all other reviewers. PRE-MORTEM never relevant. |
| **Ana** | DUTY frame anchored the PIN. UNIVERSAL test caught a real issue. | Frame dismissed when consequences clearly mattered more. |
| **Civic** | UTILITY anchored PIN. 2ND-ORDER surfaced something missed. | Frame dismissed when duty clearly mattered more. |
| **Aviva** | STRATEGIC frame cited in PIN. POSITION validated by 6-mo outcome. | Long-view ignored when short-term reality trumped it. |
| **Bob** | SANITY caught an obvious miss. IN-PRACTICE validated by reality. | OBVIOUS was already obvious to everyone. |
| **Pip** | Artifact delivered, used, kept. | Output rejected, redone. |
| **Eve** | STATUS: shipped. ESTIMATE within ±20% of actual. BLOCKER → REWORK. | ESTIMATE off by >2×. BLOCKER → RESUME (= noise). |
| **LOL** | Same as Eve, plus DEVICE passed. | SIMRUN passes, DEVICE fails. |
| **noN** | Interrupt changed direction; PIN reflects it. | Interrupt was noise; thread continued unchanged. |

This table is the only "training data" the council needs. Every pin generates one row per contributing justice; over weeks the library is rich enough that retrieval at compose-time pulls the right past work for the right inbound.

## Goal 3 — Tool-call effectiveness (Otto, Eve, LOL)

Three-step protocol around every tool call:

1. **Pre-call grounding** — one line in the transcript justifying tool + lane: *"Tool: gmail.send. Why: Dr Non asked for a draft to X. Lane: people-side."* Empty or wrong-lane justification aborts the call.
2. **Call** — execute, capture result code, output excerpt, latency.
3. **Post-call validation** — post `SENT:` (success) / `BLOCKED-EXTERNAL:` (API error) / `BLOCKER:` (call succeeded but did the wrong thing) with a one-line evidence trace.

Retry: 2× with 5s backoff for transient errors (5xx, network). Semantic errors (4xx, auth, validation) never retry — straight to `BLOCKER:`. The audit log (Lock 4 in [inter-bot-protocols.md](inter-bot-protocols.md)) gives Dr Non grep-able history; combined with the validation step, every call has a story.

## Where it lives on disk

```
~/.council/
├── transcript.jsonl                  # canonical record
├── transcript-YYYY-MM-DD.jsonl       # daily rotation
├── exemplars/
│   ├── <bot_id>/{good,bad,mixed}/<thread-id>.json
│   └── ...                            # one tree per justice
├── tool-calls.jsonl                  # Lock 4 audit log
└── drift/
    └── YYYY-Www.json                 # weekly drift output
```

Each exemplar file ≤4KB, text JSON, one per archived contribution. Per-bot retrieval index is a small SQLite + sentence-transformers DB; fits on the council Mac without a vector service.

## Unsupervised side — pattern mining

The per-week job is the unsupervised half. It does not need labels — only the transcript:

- **Cluster** each justice's contributions by embedding similarity. Surfaces unnamed patterns ("Tenet routes contracts to WORKFLOW 80% of the time, even when they are JUDGMENT").
- **Detect outliers** — contributions far from any cluster. Either novel insight or noise; flag for Dr Non to read.
- **Detect drift** — verb-distribution shift > 2σ from 4-week baseline. Flagged via a `from: "system"` line in the transcript.

Drift is the canary. A bot whose distribution silently changes is either improving, breaking, or being gamed. Surface it; let Dr Non decide.

## Failure modes & guardrails

- **Exemplar pollution.** A bad week trains bots toward bad behaviour. Mitigation: Dr Non can `rm exemplars/<bot>/bad/<id>.json`; next index rebuild forgets it.
- **Retrieval over-anchoring.** A bot parrots three similar exemplars instead of composing fresh. Mitigation: cap retrieval at 3, require composer to write — not paste.
- **Reward hacking.** A bot games the metric (Otto sends short DRAFTs that never revise but are useless). Mitigation: weekly drift detection flags the distribution shift; Dr Non spot-checks.
- **Privacy.** Exemplars contain message content. They live under `~/.council/` (local only), gitignored, and pass through the same secret-redaction (Lock 2) on append.
- **Cold start.** A new justice (LOL) has no exemplars. First week: retrieval returns nothing, the bot composes from palette + recent transcript only. Library grows from there.

## What this doc does NOT do

- **Does not retrain models.** Layerable later if Dr Non invests paid compute. Not required for the system to work.
- **Does not replace judgment-mode deliberation.** Learning accelerates the routine; novel decisions still go to council debate.
- **Does not cross bot boundaries.** Tenet's exemplars do not improve Hannah's retrieval. Each library is its own — like each justice's mind.
- **Does not run synchronously with the line.** Reflection happens after the pin; retrieval caches per-thread. The line never waits for the loop.

## Implementation order (when Dr Non is ready)

1. **`reflect.py`** — reads `transcript.jsonl`, finds new pins, scores contributions, writes exemplar files. ~150 lines. Cron-driven, every 5 min. Cheapest, biggest immediate value (the library starts populating).
2. **Self-check append** — one prompt-block added to every bot's SOUL.md. Zero infra. Catches drift today.
3. **Retrieval at compose** — each bot's harness queries the SQLite + embeddings DB before composing. Per-framework integration, like the policy.json loader work.
4. **Drift job** — weekly cron, reads exemplars/transcripts, writes `drift/YYYY-Www.json`. Lowest urgency; meaningful only after a month of data.

Steps 1 and 2 ship the unsupervised + reinforcement loops at the prompt level. Steps 3 and 4 graduate to retrieval-augmented and meta-monitoring. Each step is independently useful; none is required for the next.
