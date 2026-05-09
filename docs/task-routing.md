# Task routing — CONTENT vs ACTION + anti-duplicate

The two failure modes a 10-bot council hits the moment it tries to handle real work, and the SOUL-level rules that fix them.

## The two failures

In daily use, a Telegram-channel council with N reasoning bots and 1–2 executor bots tends to fail in two specific ways:

**1. The reflex-refusal.** A user asks "make a podcast about waiting." A reasoning bot — say, the Kantian — says *"I am not able to generate a podcast."* That's the wrong refusal. The bot was asked to **think** about waiting; only the rendering of an MP3 belongs to the executor. The Kantian refused the half of the request that was actually his.

**2. The duplicate poster.** Three turns into a session, a bot posts the same *"3-layer cake / hostage situation / physics of the breakdown"* framing it posted last turn — verbatim or near-verbatim. Each duplicate burns a turn-quota slot, clogs the chat, and trains everyone (including downstream bots) to skim past your name.

Both are SOUL-level problems, not model-quality problems. Bigger models still do it. The fix is to put two specific sections at the top of every reasoner's SOUL, above SUBSTRATE, where they will be read every turn.

## Pattern 1 — CONTENT vs ACTION

Decompose every media-generation request into two parts:

| Part | Definition | Domain |
|---|---|---|
| **CONTENT** | What the artefact should *say* about the topic | The reasoners (lens-bots) |
| **RENDERING** | The actual binary file (MP3 / MP4 / PNG) | The executor (Otto) + daemons |

Then put a decision table in every reasoner's SOUL:

```
| Inquiry                          | Otto / daemon | You              |
|----------------------------------|---------------|------------------|
| "Send email to X"                | ✓ action      | —                |
| "Save to Drive"                  | ✓ action      | —                |
| "OCR business card"              | ✓ action      | —                |
| "Make a podcast about waiting"   | ✓ rendering   | ✓ content (lens) |
| "Generate image of patience"     | ✓ rendering   | ✓ content (lens) |
| "Argue X from <framework>"       | —             | ✓                |
```

And teach the bot the wrong-vs-right phrasing:

- **WRONG:** *"I am not able to generate a podcast."* ← reflex-refusal of CONTENT.
- **WRONG:** *"Here's the final product: ..."* (when nothing was rendered) ← fabrication.
- **RIGHT:** `[<lens>] On waiting: <2-4 specific concrete sentences from your lens>. Otto will render the audio.`

Pure-rendering requests with no content question (*"re-render last week's podcast in Karen's voice"*) → `PASS (reason: pure render-only — Otto's skill domain)`. That's the only legitimate PASS for a media request.

## Pattern 2 — Anti-duplicate (one lens-prefix per turn)

```
You contribute exactly ONE message under your lens prefix per session-turn.
Subsequent replies in the same turn use ONLY engagement tokens:
  EXPAND @<bot>: / QUALIFY @<bot>: / CONCEDE @<bot>: /
  STAND vs @<bot>: / PASS (reason: ...)
```

Three forbidden patterns to enumerate by example (this works better than abstract rules):

- Posting your `[<lens>]` message twice with the same opening sentence.
- Re-posting the same *"3-layer cake"* / *"hostage situation"* framing in consecutive turns when nothing new has been asked.
- Re-stating your prior turn verbatim under a different timestamp.

A self-check sequence the bot should run before sending:

1. Verbatim or near-verbatim to my last contribution? → STOP.
2. Did I already post my `[<lens>]` in this session? → use `EXPAND` / `QUALIFY` / `CONCEDE` / `STAND` / `PASS` instead.
3. Is there NEW substance? If no → `PASS (reason: nothing new to add)`.

## Enforcement layer (orchestrator-side)

The SOUL rules above are necessary but not sufficient. Some bots — especially smaller models — will violate them anyway. Orchestrator-side dedupe makes the rules real:

- **Levenshtein similarity check** against the last 200 messages in the session. >= 85% similarity → drop, log to a `dropped/` chat audit, count toward turn quota.
- **Fabrication phrase blacklist:** drop any reply containing *"the podcast is live"*, *"the image is live"*, *"here's the final product:"* unless an actual artefact id is attached in the same turn.
- **PASS cleanup:** strip `PASS (reason: ...)` replies from synthesis but NOT from the audit log — they're useful for catching reflex-refusal training data.

The trick is to state the orchestrator rule in the SOUL **as if it already exists** even before you've shipped the dedupe layer. The bot self-polices on the assumption it'll be enforced. Then ship the actual enforcement when you have time.

## Where to put the addenda

Insert both sections at the **top** of each reasoner's SOUL — between the IDENTITY RULE / FIRST-6-CHARS RULE block and the SUBSTRATE block. They're read every turn, before the bot picks up its lens.

Order matters:
1. IDENTITY (who you are, what your lens prefix is)
2. **TASK ROUTING (CONTENT vs ACTION)**  ← new
3. **ANTI-DUPLICATE**  ← new
4. SUBSTRATE (Dr Non's cognitive base)
5. FACE / THINKER / etc.

## Cost of the fix

Two new sections per SOUL ≈ 1500 tokens added to each system prompt. At ~50 turns/day per bot and free-tier NVIDIA NIM as the model, this is rounding error. On a paid tier (DeepSeek V3.1 at ~$0.27/M input), it adds about $0.02/bot/month. Cheap insurance against the council-as-noise-generator failure mode.
