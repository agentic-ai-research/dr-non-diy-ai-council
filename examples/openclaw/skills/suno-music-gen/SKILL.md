---
name: suno-music-gen
description: "Generate music (full songs or instrumental tracks) from a text prompt. Default backend is MusicGen via Replicate (free credits at signup, then ~$0.0023/sec — functionally near-$0 for podcast intros, social clips, weekly playlists). Drops MP3 to local disk and returns the path. Optional upload to SoundCloud via the existing soundcloud-upload skill. Triggers: generate music, make a song, write me a track, podcast intro music, background score, jingle, instrumental for X."
metadata:
  openclaw:
    requires:
      bins: [python3]
      env: [REPLICATE_API_TOKEN]
  emoji: "🎵"
---

# Music Generation

Generate music tracks from a text prompt. Backend-agnostic; default is **MusicGen on Replicate** (free credits, then near-$0). Switchable to Suno (paid, higher quality) or Stable Audio (Stability AI free tier) by `--backend`.

## When to use

Triggers — *"make me a podcast intro," "write a 30-sec instrumental about X," "background score for the demo video,"* anything music-shaped that isn't just voice (use `elevenlabs` for voice).

## Usage

```bash
python3 ~/.openclaw/skills/suno-music-gen/scripts/gen.py \
  --prompt "Lo-fi hip-hop with rain sounds and soft piano. Mellow, study-friendly." \
  --duration 30 \
  --out ~/.openclaw/workspace/audio/lofi-study.mp3
```

## Backends

| Backend | Free tier | Quality | Speed | Set with |
|---|---|---|---|---|
| **MusicGen via Replicate** (default) | $0.10 free credits at signup; ~$0.0023/sec after | High for instrumentals | ~30s wait | `--backend replicate-musicgen` |
| **Suno** (via API) | None (paid only) | Highest, with vocals | ~60s wait | `--backend suno` (requires `SUNO_API_KEY`) |
| **Stable Audio** | Stability AI free tier | Medium-high | ~20s wait | `--backend stable-audio` (requires `STABILITY_API_KEY`) |

The default keeps you at $0 for everyday use; switch to Suno only when you need vocals.

## Args

| Flag | Default | Notes |
|---|---|---|
| `--prompt` | (required) | Text description of the music. Be specific about genre, mood, instruments. |
| `--duration` | `30` | Seconds. Replicate caps at 30s per call; longer = chained generations + crossfade. |
| `--out` | (required) | Output path. `.mp3` extension recommended. |
| `--backend` | `replicate-musicgen` | One of the table above. |
| `--seed` | random | For reproducibility — same seed + prompt = same track. |

## Output

A single MP3 file at `--out`. The script prints the path on success, exits non-zero on failure.

## Cost guard

Before each call, the script estimates the cost from the duration + backend pricing and refuses (`exit 2`) if the estimate exceeds `$MAX_COST` (env var, default $0.50). Override with `--no-cost-guard` for one-off generations beyond the cap.

## Chain with other skills

For a full podcast intro:

```bash
# 1. Generate the music
python3 ~/.openclaw/skills/suno-music-gen/scripts/gen.py \
  --prompt "30-sec upbeat synthwave intro, building to a drop at 0:25" \
  --duration 30 \
  --out /tmp/intro.mp3

# 2. Generate cover art
python3 ~/.openclaw/skills/fal-image-gen/scripts/gen.py \
  --prompt "Synthwave podcast cover, retro grid, sunset" \
  --aspect 1:1 \
  --out /tmp/cover.png

# 3. Upload to SoundCloud
python3 ~/.openclaw/skills/soundcloud-upload/scripts/upload.py \
  --audio /tmp/intro.mp3 --cover /tmp/cover.png \
  --title "Episode 12 Intro" --tags "podcast,synthwave"
```

Or wire it into a single pipeline skill — see `blog-to-podcast-pipeline` for the pattern.
