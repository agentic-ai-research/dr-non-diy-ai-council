---
name: fal-video-gen
description: "Generate short videos via fal.ai (Veo 3, Kling 2, Sora 2, Wan 2.5, etc). Sister skill to fal-image-gen — same CLI shape, same env (FAL_KEY), same call pattern. Returns local MP4 path. Free credits at fal.ai signup; cheapest model defaults so a 5-sec clip is a few cents. Triggers: generate video, make a clip, animate this prompt, demo video, social-media short."
metadata:
  openclaw:
    requires:
      bins: [python3]
      env: [FAL_KEY]
  emoji: "🎬"
---

# fal.ai Video Generation

Sister to `fal-image-gen`. Generates short videos (typically 4–8 seconds) from a text prompt or text+image. Output is a downloaded MP4 ready for posting to Telegram, X, YouTube Shorts, etc.

## Usage

```bash
# Text → video, default model (Wan 2.5 — cheap and fast)
python3 ~/.openclaw/skills/fal-video-gen/scripts/gen.py \
  --prompt "A small Thai food cart, steam rising, soft golden hour light, tracking camera" \
  --duration 5 \
  --aspect 16:9 \
  --out ~/.openclaw/workspace/video/foodcart.mp4

# Text+image → video (use a reference frame)
python3 ~/.openclaw/skills/fal-video-gen/scripts/gen.py \
  --prompt "Camera pulls back to reveal the whole street" \
  --image ~/.openclaw/workspace/video/foodcart-ref.png \
  --model kling-2 \
  --duration 5 \
  --out ~/.openclaw/workspace/video/foodcart-pullback.mp4
```

## Models

| `--model` | Underlying | Speed | Quality | Rough cost (5s) |
|---|---|---|---|---|
| `wan-2.5` (default) | fal-ai/wan-25-preview/text-to-video | ~30s | High | ~$0.05 |
| `kling-2` | fal-ai/kling-video/v2/master/text-to-video | ~60s | Higher | ~$0.20 |
| `veo-3` | fal-ai/veo3/text-to-video | ~120s | Highest, with audio | ~$0.50 |
| `sora-2` | fal-ai/sora-2/text-to-video | ~180s | Highest | ~$0.40 |

Defaults to `wan-2.5` to keep cost-per-clip well under $0.10. Override only when the prompt genuinely needs the better model (cinematic shots, complex motion, sound).

## Aspect ratios

| `--aspect` | When to use |
|---|---|
| `16:9` (default) | YouTube, landscape demos |
| `9:16` | Reels, Shorts, TikTok |
| `1:1` | Instagram feed |

## Args

| Flag | Default | Notes |
|---|---|---|
| `--prompt` | (required) | Be specific about subject, motion, lighting, camera. The model rewards detail. |
| `--duration` | `5` | Seconds. Most models cap at 5–10s. |
| `--aspect` | `16:9` | See table above. |
| `--out` | (required) | Output MP4 path. |
| `--model` | `wan-2.5` | One of the models above. |
| `--image` | (optional) | Path to a reference image for image-to-video. Falls back to text-only if omitted. |
| `--seed` | random | For reproducibility. |

## Cost guard

Same pattern as `suno-music-gen`. The script estimates cost from `(model rate × duration)` and refuses (`exit 2`) if the estimate exceeds `$MAX_COST` (env var, default `$0.50`). Override with `--no-cost-guard`.

## Chain with other skills

Make a 30-sec social clip end-to-end:

```bash
# 1. Generate cover frame for image-to-video (sharper than pure text-to-video)
python3 ~/.openclaw/skills/fal-image-gen/scripts/gen.py \
  --prompt "A founder at a desk, Bangkok skyline behind, late afternoon" \
  --aspect 16:9 \
  --out /tmp/founder-frame.png

# 2. Animate from that frame
python3 ~/.openclaw/skills/fal-video-gen/scripts/gen.py \
  --prompt "Camera slowly zooms in; the founder smiles and looks up" \
  --image /tmp/founder-frame.png \
  --duration 5 \
  --aspect 16:9 \
  --out /tmp/intro.mp4

# 3. Generate background music
python3 ~/.openclaw/skills/suno-music-gen/scripts/gen.py \
  --prompt "Soft cinematic ambient, hopeful" --duration 5 --out /tmp/bg.mp3

# 4. Mux audio + video with ffmpeg (already in OpenClaw's bins)
ffmpeg -i /tmp/intro.mp4 -i /tmp/bg.mp3 -c:v copy -c:a aac -shortest /tmp/final.mp4
```
