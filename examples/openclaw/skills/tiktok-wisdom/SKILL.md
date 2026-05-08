---
name: tiktok-wisdom
description: "Turn one short idea into a 60-90s vertical video — drafted in your voice, narrated by your ElevenLabs clone, illustrated with public-domain art (Met + Wikimedia), captions burned in, optional end-card, and pushed to Telegram. Triggers: 'make a tiktok about X', 'wisdom video', 'video this idea', 'short on X'."
metadata:
  openclaw:
    requires:
      bins: [python3, ffmpeg, ffprobe]
      env: [OPENAI_API_KEY, ELEVENLABS_API_KEY, ELEVEN_VOICE_ID]
    primaryEnv: ELEVENLABS_API_KEY
    emoji: "🎬"
---

# tiktok-wisdom

Turn a sentence into a TikTok-ready vertical video, in your voice, with public-domain art behind it.

## Pipeline

```
idea (+ optional blog corpus + own photos)
            ↓ gpt-4o-mini in your voice
       script + 6-8 visual cues (JSON)
            ↓
       Met Museum API → Wikimedia Commons (free, public-domain art)
            ↓
       composite per cue: filtered photo backdrop + crisp art foreground
            ↓
       ElevenLabs TTS (your cloned voice, with auto-fallback)
            ↓
       ffmpeg: Ken Burns + crossfades + burned-in captions + optional end-card
            ↓
       MP4 (1080×1920, 9:16, ~60-90s, ~6-8 MB)
            ↓
       Telegram (DM + group, optional)
```

## When to use

Triggers — *"make a tiktok about X," "wisdom video," "video this idea," "short on X."* If you have a blog corpus and care about authenticity, pass `--strict` to forbid the model from fabricating stories — it can only paraphrase the excerpts in context.

## Prerequisites

```bash
brew install ffmpeg python@3
python3 -m pip install --user Pillow

# Required env (in ~/.openclaw/.env or shell):
#   OPENAI_API_KEY      — for gpt-4o-mini script drafting
#   ELEVENLABS_API_KEY  — for TTS
#   ELEVEN_VOICE_ID     — your cloned voice ID
#
# Optional env:
#   ELEVEN_FALLBACK_VOICE_IDS  — comma-separated fallback chain if primary
#                                returns voice_not_fine_tuned
#   TG_BOT_TOKEN_FILE          — path to file containing Telegram bot token
#                                (default: ~/.openclaw/credentials/telegram-token.txt)
#   TG_DM_CHAT_ID              — your DM chat ID (numeric)
#   TG_COUNCIL_CHAT_ID         — group chat ID (numeric, negative for groups)
```

## Usage

```bash
# Minimum
python3 examples/openclaw/skills/tiktok-wisdom/scripts/build.py \
  --idea "We chase clarity like it owes us something. The most honest moments of my life have been holding two true things at once."

# With your blog corpus (a JSON list of WordPress REST posts)
python3 examples/openclaw/skills/tiktok-wisdom/scripts/build.py \
  --idea "What do you do when you feel unmotivated?" \
  --blog-corpus ~/data/myblog.json \
  --strict

# With your own photos as filtered backdrops
python3 examples/openclaw/skills/tiktok-wisdom/scripts/build.py \
  --idea "Three lessons I learned the hard way." \
  --user-photos ~/Pictures/me

# Skip Telegram push (just produce the .mp4)
python3 examples/openclaw/skills/tiktok-wisdom/scripts/build.py \
  --idea "..." --no-push
```

## Style auto-detection

The drafter picks one of two formats based on the idea:

- **listicle** — triggered by "three things," "five lessons," "ways to deal with," "what I wish I knew," "I learned the hard way," etc. Output: HOOK → One/Two/Three (each = story + 1-line lesson) → KICKER. 7 cues.
- **essay** — everything else. Two-or-three quick scenes/anecdotes → ONE sharp BANG line ≤15 words. 6 cues.

Override with `--style listicle` or `--style essay`.

## --strict mode

When `--strict` is passed:
- Pulls 7 longer blog posts into context (vs 3 short ones).
- The system prompt forbids the model from inventing names, dates, quotes, or specific scenes that aren't traceable to the BLOG: excerpts.
- Bridging prose between sourced fragments is allowed; fabrication is not.
- Better short and true than long and false — the model is told to cut beats it can't source.

Without `--strict`, the model paraphrases the excerpts and may add plausible bridging detail.

## Cost per video

| Step | Service | ~Cost |
|---|---|---|
| Script draft (~12 KB context) | OpenAI gpt-4o-mini | $0.005 |
| Art (6-8 pieces) | Met / Wikimedia | $0.00 |
| Voice (~75 s) | ElevenLabs | $0.20-0.30 |
| Video composite | ffmpeg local | $0.00 |
| **Total** | | **~$0.25** |

## Composite-image system

Each cue is a 1080×1920 composite, NOT a single image:

- **Foreground** — Met or Wikimedia Commons piece matching the cue's atmospheric query (e.g. "Bangkok monsoon," "solitary man balcony"). Crisp, scaled to ~86 % width, centered ~28 % from top so captions don't collide.
- **Background** — alternates per cue: either a filtered version of one of YOUR photos, or a second art piece. Always blurred and darkened so the foreground reads cleanly.

Eight photo-filter variants are randomized per cue: `sepia-warm`, `duotone-teal-orange`, `high-contrast-mono`, `soft-haze`, `deep-blue-cool`, `golden-hour-warm`, `muted-vintage`, `clarity-punch`. Same source photo never looks the same way twice.

## Art-source hierarchy

1. **Met Museum API** — first try, filtered by genre. CC0, no key, ~470 K objects.
2. **Wikimedia Commons** — fallback for modern subjects, broader genres.
3. **Last resort** — generic "landscape painting" if both fail.

If a cue's art search fails entirely, the previous cue's image is reused (so the video never breaks).

## Voice fallback chain

ElevenLabs Professional Voice Cloning takes hours to fine-tune. If the primary voice ID returns `voice_not_fine_tuned`, the script auto-falls-through `ELEVEN_FALLBACK_VOICE_IDS` (comma-separated). This way you can ship a "good-enough" instant clone today and seamlessly upgrade to your PVC tomorrow with no code change.

## Output

- `~/wisdom-NNN.mp4` (or wherever `--out` points)
- `wisdom-NNN.meta.json` next to it — full plan (title, script, cues) for auditing
- Working dir `wisdom-NNN-work/` — fg/bg/composite images, voice.mp3, intermediate videos

## Failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| `ELEVENLABS_API_KEY missing` | env not loaded | Check `~/.openclaw/.env` or shell |
| `voice_not_fine_tuned` | PVC clone not yet trained | Verify in dashboard; fallback auto-fires |
| `no art could be fetched` | Met + Wikimedia both timed out | Re-run; transient |
| `caption burn-in failed` | Pillow not in PATH | `pip install --user Pillow` |
| `ffmpeg failed` | Encoder issue | Read tail of stderr printed in stdout |
