#!/usr/bin/env python3
"""tiktok-wisdom — one idea → 60-90 s vertical TikTok video.

Pipeline:
  1. Read user idea + (optional) glob context folder + (optional) blog corpus
  2. Draft 60-90 s script (gpt-4o-mini in your voice) with N visual cue lines
  3. Plan visual queries from script structure
  4. Fetch public-domain art (Met → Wikimedia → fallback) for each cue
  5. Composite per cue: filtered photo backdrop + crisp art foreground
  6. Render TTS in your cloned voice (ElevenLabs) — auto-falls-through fallback
     voice IDs if primary returns voice_not_fine_tuned
  7. Stitch video: Ken Burns on each composite + 0.5 s crossfades + captions
  8. Append optional end-card image (3 s)
  9. Push to Telegram (DM + group, both optional)

Usage:
  build.py --idea "<seed>"
           [--context ~/path/to/wiki]
           [--blog-corpus ~/path/to/myblog.json]
           [--user-photos ~/Pictures/me] (repeatable)
           [--end-photo /path/to/portrait.jpg]
           [--target-seconds 75]
           [--out ~/wisdom-NN.mp4]
           [--style auto|essay|listicle]
           [--strict]
           [--no-push]
           [--no-captions]

Required env (in ~/.openclaw/.env or shell):
  OPENAI_API_KEY      — for gpt-4o-mini script drafting
  ELEVENLABS_API_KEY  — for TTS
  ELEVEN_VOICE_ID     — your cloned voice ID

Optional env:
  ELEVEN_FALLBACK_VOICE_IDS  — comma-separated fallback chain (e.g. legacy
                               instant-clone IDs to use until PVC fine-tunes)
  TG_BOT_TOKEN_FILE          — path to telegram bot token file
                               (default: ~/.openclaw/credentials/telegram-token.txt)
  TG_DM_CHAT_ID              — your DM chat ID (numeric, positive)
  TG_COUNCIL_CHAT_ID         — group chat ID (numeric, negative)
"""
from __future__ import annotations

import argparse, glob, json, os, random, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

# Local lib (sibling dir; works for both `python build.py` and `from-package`)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cache as _cache  # noqa: E402


# ── 0. config loader (optional --config <path>.toml) ─────────────────────
def load_config_file(path: Path) -> dict:
    """Load a TOML or JSON config file. Returns flat dict of kwargs that
    will be merged with argparse defaults (CLI flags still override).
    Schema mirrors argparse `dest` names: idea, voice_provider, voice_id,
    style, strict, persona, blog_corpus, user_photos, no_push, etc."""
    if not path.exists():
        raise FileNotFoundError(f"--config: {path} not found")
    if path.suffix.lower() in (".toml", ""):
        try:
            import tomllib   # Python 3.11+
        except ImportError:
            try:
                import tomli as tomllib   # type: ignore
            except ImportError:
                raise RuntimeError(
                    "TOML config needs Python 3.11+ (tomllib stdlib) "
                    "or `pip install tomli`. JSON configs work everywhere."
                )
        with path.open("rb") as f:
            return tomllib.load(f)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    raise RuntimeError(f"--config: unsupported extension {path.suffix} "
                       f"(use .toml or .json)")

# ── config ────────────────────────────────────────────────────────────────
ENV_FILE         = Path.home() / ".openclaw" / ".env"
DEFAULT_OUT_DIR  = Path.home() / "Brain" / "Council" / "Videos" / "wisdom"
DEFAULT_TG_TOKEN_FILE = Path.home() / ".openclaw" / "credentials" / "telegram-token.txt"
# Vertical 1080×1920 is full TikTok-spec.
WIDTH, HEIGHT    = 1080, 1920


def load_env() -> dict:
    """Merge ~/.openclaw/.env with the shell env (shell wins)."""
    env: dict = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in (
        "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ELEVEN_VOICE_ID",
        "ELEVEN_FALLBACK_VOICE_IDS",
        "TG_BOT_TOKEN_FILE", "TG_DM_CHAT_ID", "TG_COUNCIL_CHAT_ID",
    ):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _strip_html(s: str) -> str:
    """Cheap HTML stripper — WordPress content is fairly clean."""
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<script[^>]*>.*?</script>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;|&#8217;|&#8220;|&#8221;|&#8211;|&#8212;|&amp;", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def gather_context(idea: str, ctx_dir: Path | None,
                   blog_corpus: Path | None = None,
                   max_chars: int = 12000,
                   strict: bool = False) -> str:
    """Score-rank blog posts (and optional wiki dir) against the idea
    and return the top excerpts as one concatenated context blob.

    Sources, in priority order:
      1. blog_corpus — JSON list of WordPress REST posts (each with
         ``{"title": {"rendered": ...}, "content": {"rendered": ...}}``).
      2. ctx_dir — *.md/*.txt summaries (a wiki you keep).

    Scoring is dumb-but-effective: idea-word matches in title (3× weight)
    plus matches anywhere in the body (1×). Top-N posts up to max_chars total.
    """
    idea_words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", idea)}
    parts: list[str] = []
    used = 0

    # Source 1: blog corpus ─────────────────────────────────────────────
    posts: list[tuple[int, str, str]] = []   # (score, title, body)
    if blog_corpus and blog_corpus.exists():
        try:
            entries = json.loads(blog_corpus.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [context] blog corpus parse failed: {e}", file=sys.stderr)
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = ((entry.get("title") or {}).get("rendered") or "").strip()
            html  = ((entry.get("content") or {}).get("rendered") or "")
            body  = _strip_html(html)
            if not body:
                continue
            tlow = title.lower()
            blow = body.lower()
            score = sum(3 for w in idea_words if w in tlow)
            score += sum(1 for w in idea_words if w in blow)
            posts.append((score, title, body))
        posts.sort(key=lambda x: -x[0])
        relevant = [p for p in posts if p[0] > 0]
        # Strict mode pulls more posts and longer excerpts: the model is
        # forbidden from inventing, so we need enough sourced material.
        if strict:
            chosen = relevant[:7] if relevant else posts[:5]
            per_post_chars = 4500
        else:
            chosen = relevant[:3] if relevant else posts[:2]
            per_post_chars = 2400
        for score, title, body in chosen:
            chunk = f"\n## BLOG: {title}\n{body[:per_post_chars]}\n"
            if used + len(chunk) > max_chars:
                break
            parts.append(chunk)
            used += len(chunk)
        if chosen:
            print(f"  [context] {len(chosen)} blog post(s) chosen "
                  f"(top score: {chosen[0][0]}, title: {chosen[0][1][:60]})",
                  file=sys.stderr)

    # Source 2: wiki dir ────────────────────────────────────────────────
    if ctx_dir and ctx_dir.exists() and used < max_chars:
        files = sorted(ctx_dir.glob("**/*.md")) + sorted(ctx_dir.glob("**/*.txt"))
        scored_files: list[tuple[int, Path, str]] = []
        for f in files:
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:1500]
            except Exception:
                continue
            fname_lc = f.stem.lower()
            head_lc = head.lower()
            score = sum(3 for w in idea_words if w in fname_lc)
            score += sum(1 for w in idea_words if w in head_lc)
            scored_files.append((score, f, head))
        scored_files.sort(key=lambda s: -s[0])
        added = 0
        for score, f, head in scored_files:
            if score == 0 and added >= 2:
                break
            chunk = f"\n## WIKI: {f.stem}\n{head[:600]}\n"
            if used + len(chunk) > max_chars:
                break
            parts.append(chunk)
            used += len(chunk)
            added += 1

    return "\n".join(parts)


# ── 2. script draft ──────────────────────────────────────────────────────
# Prompts live in ../prompts/*.md so anyone can edit voice/style/persona
# without touching code. To ship a different persona for a different user,
# drop a new file in prompts/personas/<name>.md and pass --persona <name>.
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str, fallback: str = "") -> str:
    """Load a prompt file from ../prompts/. Return fallback on miss."""
    p = PROMPTS_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return fallback


def load_persona(name: str) -> str:
    """Load a persona overlay from ../prompts/personas/<name>.md.
    Returns empty string for the default 'plain' persona or any miss."""
    p = PROMPTS_DIR / "personas" / f"{name}.md"
    if not p.exists() or name in ("", "plain", "none"):
        return ""
    return p.read_text(encoding="utf-8")


_LISTICLE_TRIGGERS = (
    r"\b(three|four|five|six|seven|eight|nine|ten|3|4|5|6|7|8|9|10)\b",
    r"\b(things?|ways?|lessons?|reasons?|rules?|tips?|mistakes?|signs?|truths?|habits?)\b",
    r"\b(I (wish|should|could)( have)?\s+(I?\s*)?(known|knew|learned|done))\b",
    r"\bhow to deal with\b",
    r"\bI learned the hard way\b",
    r"\bif I could (go back|tell)\b",
)


def detect_style(idea: str) -> str:
    """Auto-detect 'listicle' if the idea has a number-of-items + things/ways/lessons.
    Falls back to 'essay'."""
    text = idea.lower()
    has_number = bool(re.search(_LISTICLE_TRIGGERS[0], text))
    has_listy_noun = bool(re.search(_LISTICLE_TRIGGERS[1], text))
    has_phrase = any(re.search(p, text, re.I) for p in _LISTICLE_TRIGGERS[2:])
    if (has_number and has_listy_noun) or has_phrase:
        return "listicle"
    return "essay"


def draft_script(idea: str, context: str, openai_key: str,
                 style: str = "auto", strict: bool = False,
                 persona: str = "plain") -> dict:
    if style == "auto":
        style = detect_style(idea)
    voice_preamble = _load_prompt("voice-preamble.md")
    persona_overlay = load_persona(persona)
    fmt_file = "style-listicle.md" if style == "listicle" else "style-essay.md"
    fmt = _load_prompt(fmt_file)
    system = voice_preamble
    if persona_overlay:
        system += "\n\n" + persona_overlay
    system += "\n\n" + fmt
    if strict:
        system += "\n\n" + _load_prompt("strict-addendum.md")
    print(f"  [style] {style}{' [strict]' if strict else ''}"
          f"{' [persona='+persona+']' if persona and persona != 'plain' else ''}",
          file=sys.stderr)

    if strict:
        usage_note = (
            "RELATED CONTEXT FROM THE BLOG (the ONLY source of specific stories,\n"
            "names, places, quotes, and claims you may use. Anything in the script\n"
            "must be traceable to one of these BLOG excerpts. If they don't\n"
            "support a beat, cut the beat — do not invent to fill space):"
        )
    else:
        usage_note = (
            "RELATED CONTEXT FROM THE BLOG/WIKI (use selectively — pull SPECIFIC\n"
            "stories, don't summarize):"
        )
    user_prompt = (
        f"USER'S IDEA:\n{idea.strip()}\n\n"
        f"{usage_note}\n{context.strip() or '(none)'}\n\n"
        f"Write the script now. JSON only."
    )
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "max_tokens": 1800,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read())
    raw = data["choices"][0]["message"]["content"]
    plan = json.loads(raw)
    plan["_style"] = style
    return plan


# ── 3. art fetch (Met → Wikimedia → fallback) ────────────────────────────
def met_search(query: str, want_genre: str = "painting") -> str | None:
    q = urllib.parse.quote(query)
    medium = ""
    if want_genre == "painting":
        medium = "&medium=Paintings"
    elif want_genre == "sculpture":
        medium = "&medium=Sculpture"
    url = f"https://collectionapi.metmuseum.org/public/collection/v1/search?q={q}&hasImages=true{medium}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [met] search '{query}' failed: {e}", file=sys.stderr)
        return None
    ids = data.get("objectIDs") or []
    if not ids:
        return None
    random.shuffle(ids)
    for obj_id in ids[:8]:
        obj_url = f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{obj_id}"
        try:
            with urllib.request.urlopen(obj_url, timeout=15) as r:
                obj = json.loads(r.read())
        except Exception:
            continue
        img = obj.get("primaryImage") or obj.get("primaryImageSmall")
        if img:
            print(f"  [met] '{query}' → {obj.get('title','?')[:40]} by "
                  f"{obj.get('artistDisplayName','?')[:30]}", file=sys.stderr)
            return img
    return None


def wikimedia_search(query: str) -> str | None:
    q = urllib.parse.quote(query + " painting")
    url = (f"https://commons.wikimedia.org/w/api.php?action=query&format=json"
           f"&list=search&srsearch={q}&srnamespace=6&srlimit=10")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [wiki] search '{query}' failed: {e}", file=sys.stderr)
        return None
    hits = data.get("query", {}).get("search", [])
    for hit in hits:
        title = hit.get("title", "")
        if not title.startswith("File:"):
            continue
        info_url = (f"https://commons.wikimedia.org/w/api.php?action=query&format=json"
                    f"&titles={urllib.parse.quote(title)}&prop=imageinfo&iiprop=url&iiurlwidth=1200")
        try:
            with urllib.request.urlopen(info_url, timeout=15) as r:
                info = json.loads(r.read())
            pages = info.get("query", {}).get("pages", {})
            for _, p in pages.items():
                ii = p.get("imageinfo", [{}])[0]
                u = ii.get("thumburl") or ii.get("url")
                if u and any(u.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                    print(f"  [wiki] '{query}' → {title[:50]}", file=sys.stderr)
                    return u
        except Exception:
            continue
    return None


def download_image(url: str, out_path: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tiktok-wisdom/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        if len(body) < 5000:
            return False
        out_path.write_bytes(body)
        return True
    except Exception as e:
        print(f"  download failed: {e}", file=sys.stderr)
        return False


def _list_user_photos(photos_dirs: list[Path]) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".heic", ".HEIC", ".webp"}
    out: list[Path] = []
    for d in photos_dirs:
        if not d or not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix in exts:
                out.append(f)
    return sorted(out)


def _convert_heic(src: Path, dst: Path) -> bool:
    """Use sips (macOS) to convert HEIC → JPG."""
    try:
        r = subprocess.run(
            ["sips", "-s", "format", "jpeg", str(src), "--out", str(dst)],
            capture_output=True, text=True,
        )
        return r.returncode == 0 and dst.exists()
    except Exception:
        return False


def _apply_random_filter(img, seed: int):
    """Apply ONE of N filters chosen by seed. Used so the same source photo
    never looks the same way twice across cues."""
    try:
        from PIL import ImageEnhance, ImageOps, ImageFilter
    except ImportError:
        return img
    random.seed(seed)
    filt = random.choice([
        "sepia-warm", "duotone-teal-orange", "high-contrast-mono",
        "soft-haze", "deep-blue-cool", "golden-hour-warm",
        "muted-vintage", "clarity-punch",
    ])
    if filt == "sepia-warm":
        gray = ImageOps.grayscale(img)
        sepia = ImageOps.colorize(gray, black=(60, 38, 22), white=(255, 235, 210))
        return ImageEnhance.Contrast(sepia).enhance(1.05)
    if filt == "duotone-teal-orange":
        gray = ImageOps.grayscale(img)
        return ImageOps.colorize(gray, black=(15, 50, 70), white=(255, 178, 130))
    if filt == "high-contrast-mono":
        gray = ImageOps.grayscale(img).convert("RGB")
        return ImageEnhance.Contrast(gray).enhance(1.45)
    if filt == "soft-haze":
        h = img.filter(ImageFilter.GaussianBlur(radius=2))
        h = ImageEnhance.Brightness(h).enhance(1.05)
        h = ImageEnhance.Color(h).enhance(0.85)
        return h
    if filt == "deep-blue-cool":
        gray = ImageOps.grayscale(img)
        return ImageOps.colorize(gray, black=(10, 20, 50), white=(180, 200, 230))
    if filt == "golden-hour-warm":
        e = ImageEnhance.Color(img).enhance(1.3)
        e = ImageEnhance.Brightness(e).enhance(1.05)
        r, g, b = e.split()
        r = r.point(lambda v: min(255, int(v * 1.08)))
        b = b.point(lambda v: int(v * 0.92))
        from PIL import Image as _I
        return _I.merge("RGB", (r, g, b))
    if filt == "muted-vintage":
        e = ImageEnhance.Color(img).enhance(0.55)
        return ImageEnhance.Contrast(e).enhance(0.92)
    if filt == "clarity-punch":
        e = ImageEnhance.Sharpness(img).enhance(1.5)
        return ImageEnhance.Contrast(e).enhance(1.15)
    return img


def fetch_art_for_cues(cues: list[dict], work_dir: Path,
                       user_photos: list[Path] | None = None) -> list[Path]:
    """For each cue, build ONE composite image that mixes 2 sources:
       - foreground: a Met/Wikimedia art piece matching the cue's atmospheric query
       - background: every-other-cue, one of the user's photos with a random
         filter; otherwise a second art piece. Always blurred + darkened.

    Returns ordered list of composite image paths. If a cue can't be resolved,
    falls back to single-image so the video never breaks."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        print("ERROR: Pillow not installed. `pip install --user Pillow`", file=sys.stderr)
        raise

    work_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    user_photos = user_photos or []
    photo_idx = 0

    for i, cue in enumerate(cues):
        query = cue.get("query", "art")
        genre = cue.get("art_genre", "painting")
        fg_path = work_dir / f"fg-{i:02d}.jpg"
        bg_path = work_dir / f"bg-{i:02d}.jpg"
        out = work_dir / f"composite-{i:02d}.jpg"

        url = met_search(query, genre) or wikimedia_search(query)
        ok_fg = bool(url) and download_image(url, fg_path)
        if not ok_fg and out_paths:
            shutil.copy(out_paths[-1], out)
            out_paths.append(out)
            print(f"  [cue {i}] '{query}' — reused previous (art search failed)", file=sys.stderr)
            continue
        if not ok_fg:
            u2 = met_search("landscape painting") or wikimedia_search("landscape painting")
            if u2 and download_image(u2, fg_path):
                ok_fg = True
        if not ok_fg:
            print(f"  [cue {i}] FAILED entirely", file=sys.stderr)
            continue

        ok_bg = False
        used_user_photo = False
        if user_photos and (i % 2 == 1):
            src = user_photos[photo_idx % len(user_photos)]
            photo_idx += 1
            if src.suffix.lower() == ".heic":
                if _convert_heic(src, bg_path):
                    ok_bg = True
            else:
                try:
                    shutil.copy(src, bg_path); ok_bg = True
                except Exception:
                    pass
            used_user_photo = ok_bg
        if not ok_bg:
            u3 = met_search(query, genre) or met_search(query.split()[0] if query else "art", genre)
            if u3 and download_image(u3, bg_path):
                ok_bg = True

        try:
            from PIL import ImageEnhance
            bg_img = Image.open(bg_path if ok_bg else fg_path).convert("RGB")
            bg_img = _resize_cover(bg_img, WIDTH, HEIGHT)
            if used_user_photo:
                bg_img = _apply_random_filter(bg_img, seed=i + int(time.time()))
            bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=22))
            bg_img = ImageEnhance.Brightness(bg_img).enhance(0.6)

            fg_img = Image.open(fg_path).convert("RGB")
            target_w = int(WIDTH * 0.86)
            fg_img = _resize_within(fg_img, target_w, int(HEIGHT * 0.7))
            x = (WIDTH - fg_img.width) // 2
            y = int(HEIGHT * 0.18)
            bg_img.paste(fg_img, (x, y))
            bg_img.save(out, quality=90)
            tag = "user-photo bg (filtered)" if used_user_photo else "art-on-art"
            print(f"  [cue {i}] '{query}' → composite ({tag})", file=sys.stderr)
            out_paths.append(out)
        except Exception as e:
            print(f"  [cue {i}] composite failed ({e}); using fg-only", file=sys.stderr)
            shutil.copy(fg_path, out)
            out_paths.append(out)
    return out_paths


def _resize_cover(img, target_w: int, target_h: int):
    w, h = img.size
    scale = max(target_w / w, target_h / h)
    new_size = (int(w * scale), int(h * scale))
    img = img.resize(new_size, 1)
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _resize_within(img, max_w: int, max_h: int):
    w, h = img.size
    scale = min(max_w / w, max_h / h)
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, 1)


# ── 4. TTS — multi-provider with free-tier first ─────────────────────────
def _mac_say_tts(text: str, out_path: Path, voice: str = "Daniel") -> tuple[bool, str]:
    """macOS `say` → AIFF → ffmpeg → MP3. Free, offline, no API key.
    Available voices: `say -v ?` (Daniel, Alex, Karen, Samantha, Tom, etc.).
    Quality is NOT comparable to ElevenLabs — this is the zero-friction
    path so you can ship your first video in 5 minutes."""
    if shutil.which("say") is None:
        return False, "macOS `say` not available (Linux/Windows host)"
    aiff = out_path.with_suffix(".aiff")
    try:
        r = subprocess.run(
            ["say", "-v", voice, "-o", str(aiff), text],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            return False, f"say failed: {r.stderr[:300]}"
        # Convert AIFF → MP3
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-i", str(aiff),
             "-c:a", "libmp3lame", "-b:a", "128k", str(out_path)],
            capture_output=True, text=True, timeout=120,
        )
        aiff.unlink(missing_ok=True)
        if r2.returncode != 0:
            return False, f"ffmpeg AIFF→MP3 failed: {r2.stderr[-300:]}"
        return out_path.exists(), ""
    except Exception as e:
        return False, str(e)[:300]


def _openai_tts(api_key: str, voice: str, text: str, out_path: Path) -> tuple[bool, str]:
    """OpenAI tts-1 — paid but cheap (~$0.015 / minute), 6 voices,
    no clone setup. Voices: alloy, echo, fable, onyx, nova, shimmer."""
    body = json.dumps({
        "model": "tts-1",
        "voice": voice or "onyx",
        "input": text,
        "response_format": "mp3",
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            audio = r.read()
        if len(audio) < 1024:
            return False, f"too small ({len(audio)} bytes)"
        out_path.write_bytes(audio)
        return True, ""
    except urllib.error.HTTPError as e:
        try: err = e.read().decode("utf-8", errors="replace")
        except Exception: err = str(e)
        return False, err[:500]
    except Exception as e:
        return False, str(e)[:500]


def _eleven_tts(api_key: str, voice_id: str, text: str, out_path: Path) -> tuple[bool, str]:
    """Single TTS attempt. Returns (ok, error_text)."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            audio = r.read()
        if len(audio) < 1024:
            return False, f"response too small ({len(audio)} bytes)"
        out_path.write_bytes(audio)
        return True, ""
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8", errors="replace")
        except Exception:
            err = str(e)
        return False, err[:500]
    except Exception as e:
        return False, str(e)[:500]


def render_tts(script_text: str, provider: str, voice_id: str,
               out_path: Path, env: dict) -> float:
    """Multi-provider TTS dispatch with auto-fallback chain.

    Providers (try in order, falling back on failure):
      - 'mac-say'   → macOS `say` command. Free, offline. Default for the
                      free-tier path. Voice = system voice name (Daniel,
                      Alex, Karen, etc.). `say -v ?` to list.
      - 'openai'    → OpenAI tts-1, voice = alloy|echo|fable|onyx|nova|shimmer.
                      ~$0.015 / min. Needs OPENAI_API_KEY.
      - 'eleven'    → ElevenLabs (paid, voice cloning). Needs
                      ELEVENLABS_API_KEY + voice_id. Auto-falls-through
                      ELEVEN_FALLBACK_VOICE_IDS if primary returns
                      voice_not_fine_tuned.

    Returns audio duration in seconds.
    """
    last_err = ""
    if provider == "mac-say":
        ok, err = _mac_say_tts(script_text, out_path, voice=voice_id or "Daniel")
        if not ok:
            last_err = err
            raise RuntimeError(f"mac-say TTS failed: {err}")

    elif provider == "openai":
        if not env.get("OPENAI_API_KEY"):
            raise RuntimeError("provider=openai needs OPENAI_API_KEY")
        ok, err = _openai_tts(env["OPENAI_API_KEY"], voice_id or "onyx",
                              script_text, out_path)
        if not ok:
            raise RuntimeError(f"openai TTS failed: {err}")

    elif provider == "eleven":
        if not env.get("ELEVENLABS_API_KEY"):
            raise RuntimeError("provider=eleven needs ELEVENLABS_API_KEY")
        if not voice_id:
            raise RuntimeError("provider=eleven needs --voice-id or ELEVEN_VOICE_ID")
        fallbacks = [v.strip() for v in (env.get("ELEVEN_FALLBACK_VOICE_IDS") or "").split(",") if v.strip()]
        chain = [voice_id] + [v for v in fallbacks if v != voice_id]
        for vid in chain:
            ok, err = _eleven_tts(env["ELEVENLABS_API_KEY"], vid, script_text, out_path)
            if ok:
                if vid != voice_id:
                    print(f"  [tts] primary voice {voice_id[:8]} failed; "
                          f"used fallback {vid[:8]}", file=sys.stderr)
                break
            last_err = err
            if "not fine-tuned" not in err and "voice_not_fine_tuned" not in err:
                raise RuntimeError(f"eleven TTS failed: {err}")
            print(f"  [tts] voice {vid[:8]} not fine-tuned — trying fallback",
                  file=sys.stderr)
        else:
            raise RuntimeError(f"eleven TTS failed across all voices "
                               f"({len(chain)} tried): {last_err}")
    else:
        raise RuntimeError(f"unknown TTS provider: {provider!r}. "
                           f"Choose: mac-say | openai | eleven")

    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out_path)],
        capture_output=True, text=True,
    )
    return float(p.stdout.strip() or "0")


# ── 5. video composite (multi-image Ken Burns + crossfades + end card) ───
def split_script_for_captions(script: str, n_segments: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", script.strip())
    if len(sentences) <= n_segments:
        return sentences
    per = max(1, len(sentences) // n_segments)
    chunks = []
    i = 0
    while i < len(sentences):
        chunks.append(" ".join(sentences[i:i+per]))
        i += per
    return chunks


def build_video(art_paths: list[Path], audio_path: Path, duration: float,
                end_card: Path | None, out_path: Path,
                title: str = "") -> None:
    """ffmpeg compose: Ken Burns on each piece + 0.5 s crossfades + audio + end-card."""
    n_art = len(art_paths)
    if n_art == 0:
        raise RuntimeError("no art images to compose")

    end_card_dur = 3.0 if end_card and end_card.exists() else 0.0
    art_total = max(duration - end_card_dur, duration * 0.85)
    per_art = art_total / n_art

    cmd = ["ffmpeg", "-y"]
    for p in art_paths:
        cmd += ["-loop", "1", "-t", f"{per_art:.2f}", "-i", str(p)]
    if end_card and end_card.exists():
        cmd += ["-loop", "1", "-t", f"{end_card_dur:.2f}", "-i", str(end_card)]
    cmd += ["-i", str(audio_path)]

    parts: list[str] = []
    for i in range(n_art):
        frames = max(int(per_art * 30), 30)
        parts.append(
            f"[{i}:v]scale={WIDTH*2}:{HEIGHT*2}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH*2}:{HEIGHT*2},"
            f"zoompan=z='min(zoom+0.0008,1.15)':d={frames}:s={WIDTH}x{HEIGHT}:fps=30,"
            f"setsar=1[v{i}]"
        )
    if end_card and end_card.exists():
        parts.append(
            f"[{n_art}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30[ve]"
        )
    XFADE_DUR = 0.5
    n_clips = n_art + (1 if end_card and end_card.exists() else 0)
    if n_clips == 1:
        parts.append("[v0]copy[vall]")
    else:
        cur = "[v0]"
        offset = per_art
        for i in range(1, n_clips):
            in_label = "[ve]" if (i == n_clips - 1 and end_card and end_card.exists()) else f"[v{i}]"
            out_label = f"[vx{i}]" if i < n_clips - 1 else "[vall]"
            xfade_off = max(offset - XFADE_DUR, 0.1)
            parts.append(f"{cur}{in_label}xfade=transition=fade:duration={XFADE_DUR}:offset={xfade_off}{out_label}")
            cur = out_label
            offset += (end_card_dur if (i == n_clips - 1 and end_card and end_card.exists()) else per_art) - XFADE_DUR
    parts.append("[vall]eq=saturation=1.1:contrast=1.05,vignette=PI/5[vfinal]")
    filter_str = ";".join(parts)

    audio_input_idx = n_art + (1 if end_card_dur > 0 else 0)
    cmd += [
        "-filter_complex", filter_str,
        "-map", "[vfinal]",
        "-map", f"{audio_input_idx}:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-r", "30",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"  [ffmpeg] composing {n_art} art pieces + end-card → {out_path.name}", file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.splitlines()[-30:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


# ── 6. caption burn-in ───────────────────────────────────────────────────
def burn_captions(video_in: Path, video_out: Path, caption_chunks: list[str],
                  total_duration: float) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("ERROR: Pillow not installed. `pip install --user Pillow`", file=sys.stderr)
        raise

    work = video_in.parent / "captions"
    work.mkdir(parents=True, exist_ok=True)
    n = len(caption_chunks)
    per = total_duration / n
    font_path = "/System/Library/Fonts/HelveticaNeue.ttc"
    if not Path(font_path).exists():
        font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 56)
    except Exception:
        font = ImageFont.load_default()

    overlay_args = []
    for i, chunk in enumerate(caption_chunks):
        png = work / f"cap-{i:02d}.png"
        img = Image.new("RGBA", (WIDTH, 360), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        words = chunk.split()
        lines: list[str] = []
        cur: list[str] = []
        for w in words:
            test = " ".join(cur + [w])
            if d.textlength(test, font=font) > WIDTH * 0.9:
                if cur:
                    lines.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(" ".join(cur))
        y = 30
        for ln in lines[:4]:
            tw = d.textlength(ln, font=font)
            x = (WIDTH - tw) / 2
            pad = 14
            d.rectangle(
                [(x - pad, y - 6), (x + tw + pad, y + 64)],
                fill=(0, 0, 0, 180),
            )
            for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
                d.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 255))
            d.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
            y += 68
        img.save(png)
        overlay_args.append((png, i * per, (i + 1) * per))

    cmd = ["ffmpeg", "-y", "-i", str(video_in)]
    for png, _, _ in overlay_args:
        cmd += ["-i", str(png)]
    parts = []
    cur_label = "[0:v]"
    for i, (_, t0, t1) in enumerate(overlay_args):
        next_label = f"[ov{i}]"
        parts.append(
            f"{cur_label}[{i+1}:v]overlay=x=0:y=H-h-200:enable='between(t,{t0:.2f},{t1:.2f})'{next_label}"
        )
        cur_label = next_label
    filter_str = ";".join(parts)
    cmd += [
        "-filter_complex", filter_str,
        "-map", cur_label,
        "-map", "0:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
        "-c:a", "copy",
        str(video_out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.splitlines()[-30:])
        raise RuntimeError(f"caption burn-in failed:\n{tail}")


# ── 6b. HTML preview (--draft-only) ──────────────────────────────────────
def write_preview_html(plan: dict, out_path: Path, idea: str,
                       provider: str, voice_id: str) -> None:
    """Write a single self-contained HTML preview of the script + cues +
    estimated cost. Lets you iterate on the IDEA before paying for TTS."""
    title  = plan.get("title", "Wisdom")
    script = plan.get("script", "")
    cues   = plan.get("visual_cues", [])
    style  = plan.get("_style", "essay")
    word_count = len(script.split())
    est_seconds = word_count / 2.5  # 150 wpm
    if provider == "eleven":
        est_cost = max(0.10, est_seconds * 0.005)   # ~$0.30 / min
    elif provider == "openai":
        est_cost = (est_seconds / 60) * 0.015        # $0.015 / min
    else:
        est_cost = 0.0
    est_cost += 0.005  # gpt-4o-mini drafting

    cue_rows = "\n".join(
        f"<tr><td>{c.get('timestamp_pct', 0):.2f}</td>"
        f"<td><code>{c.get('query','')}</code></td>"
        f"<td>{c.get('art_genre','')}</td></tr>"
        for c in cues
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Preview — {title}</title>
<style>
  body {{ font: 16px/1.5 -apple-system,system-ui,sans-serif; max-width: 720px;
         margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .meta {{ color: #666; font-size: .9rem; margin-bottom: 1.5rem; }}
  .script {{ background: #f7f7f5; padding: 1rem 1.25rem; border-left: 3px solid #888;
             white-space: pre-wrap; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
  td, th {{ padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }}
  th {{ background: #fafafa; font-weight: 600; }}
  .cost {{ background: #fffbe5; padding: .75rem 1rem; border: 1px solid #f0e090;
           border-radius: 4px; margin-top: 1.5rem; font-size: .9rem; }}
  code {{ font-family: 'SF Mono', Menlo, monospace; font-size: .85rem; }}
</style></head><body>
<h1>{title}</h1>
<div class="meta">style: <b>{style}</b> · ~{est_seconds:.0f}s · {word_count} words ·
  voice: <code>{provider}/{voice_id or '(default)'}</code></div>
<h2>Script</h2>
<div class="script">{script}</div>
<h2>Visual cues ({len(cues)})</h2>
<table><tr><th>at</th><th>query</th><th>genre</th></tr>{cue_rows}</table>
<div class="cost"><b>Estimated full-render cost:</b> ~${est_cost:.3f}
  <br><small>(LLM draft + TTS; art and ffmpeg are free.)</small></div>
<h2>Idea</h2>
<div class="meta">{idea}</div>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


# ── 7. Telegram push ──────────────────────────────────────────────────────
def push_to_telegram(video_path: Path, caption: str, chats: list[int],
                     token_file: Path) -> None:
    if not token_file.exists():
        print("  [tg] no token file; skipping push", file=sys.stderr)
        return
    if not chats:
        print("  [tg] no chats configured; skipping push", file=sys.stderr)
        return
    token = token_file.read_text().strip()
    for chat in chats:
        cmd = [
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{token}/sendVideo",
            "-F", f"chat_id={chat}",
            "-F", f"video=@{video_path}",
            "-F", f"caption={caption}",
            "-F", "supports_streaming=true",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = '"ok":true' in r.stdout
        mid_match = re.search(r'"message_id":(\d+)', r.stdout)
        mid = mid_match.group(1) if mid_match else "?"
        label = "DM" if chat > 0 else "group"
        print(f"  [tg] {label}: {'OK' if ok else 'FAIL'} msg_id={mid}", file=sys.stderr)


# ── main ──────────────────────────────────────────────────────────────────
def main() -> int:
    # Pre-pass for --config so we can use its values as argparse defaults.
    # This makes the precedence: CLI flag > config file > argparse default.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    pre_ns, _ = pre.parse_known_args()
    cfg: dict = {}
    if pre_ns.config:
        cfg = load_config_file(Path(pre_ns.config).expanduser())

    p = argparse.ArgumentParser()
    p.add_argument("--config", default="",
                   help="TOML or JSON config file with default values for any "
                        "of the flags below. CLI flags override config values. "
                        "See configs/ for examples.")
    # `idea` is required UNLESS provided in the config file.
    p.add_argument("--idea", required="idea" not in cfg, default=cfg.get("idea", ""),
                   help="Seed idea / quote / topic")
    p.add_argument("--context", default=cfg.get("context", ""),
                   help="Folder to glob for related wiki/summary files (*.md, *.txt)")
    p.add_argument("--blog-corpus", default=cfg.get("blog_corpus", ""),
                   help="Path to a JSON list of WordPress REST posts: each entry "
                        "{title:{rendered}, content:{rendered}}")
    p.add_argument("--user-photos", action="append",
                   default=cfg.get("user_photos") or None,
                   help="Folder of your photos to mix in as filtered backdrops "
                        "(repeatable). Skipped if not provided.")
    p.add_argument("--end-photo", default=cfg.get("end_photo", ""),
                   help="End-card image path. Empty to skip.")
    p.add_argument("--out", default=cfg.get("out") or None,
                   help="Output .mp4 path. "
                        "Default: ~/Brain/Council/Videos/wisdom/wisdom-NN.mp4")
    p.add_argument("--target-seconds", type=int,
                   default=cfg.get("target_seconds", 75))
    p.add_argument("--voice-provider", choices=["mac-say", "openai", "eleven"],
                   default=cfg.get("voice_provider", "mac-say"),
                   help="TTS provider. 'mac-say' is free + offline (default). "
                        "'openai' is ~$0.015/min. 'eleven' is ~$0.30/min with "
                        "voice cloning.")
    p.add_argument("--voice-id", default=cfg.get("voice_id", ""),
                   help="Voice identifier. mac-say: system voice name "
                        "(Daniel/Alex/Karen/etc). openai: alloy|echo|fable|"
                        "onyx|nova|shimmer. eleven: voice_id from your "
                        "ElevenLabs account.")
    p.add_argument("--persona", default=cfg.get("persona", "plain"),
                   help="Persona overlay file (prompts/personas/<name>.md). "
                        "Examples: plain, bangkok-architect, startup-founder.")
    p.add_argument("--style", choices=["auto", "essay", "listicle"],
                   default=cfg.get("style", "auto"),
                   help="Script format. auto detects 'listicle' from idea.")
    p.add_argument("--strict", action="store_true",
                   default=cfg.get("strict", False),
                   help="STRICT-SOURCE mode: script must use only stories/quotes "
                        "from the blog corpus. No invented anecdotes, names, or "
                        "quotes. Pulls 7 longer posts into context (vs 3 short).")
    p.add_argument("--draft-only", action="store_true",
                   default=cfg.get("draft_only", False),
                   help="Draft script + cues, write an HTML preview, then STOP. "
                        "Lets you iterate on the idea before paying for TTS+ffmpeg.")
    p.add_argument("--no-cache", action="store_true",
                   default=cfg.get("no_cache", False),
                   help="Disable stage cache; recompute everything from scratch.")
    p.add_argument("--from-cache", choices=list(_cache.STAGES_IN_ORDER),
                   default=cfg.get("from_cache", ""), metavar="STAGE",
                   help="Invalidate cache from STAGE onward and re-run. "
                        "Stages: context|script|art|tts|video|captions|final. "
                        "Use this when TTS failed and you want to retry without "
                        "re-fetching art (--from-cache tts).")
    p.add_argument("--no-push", action="store_true",
                   default=cfg.get("no_push", False),
                   help="Skip Telegram push")
    p.add_argument("--no-captions", action="store_true",
                   default=cfg.get("no_captions", False),
                   help="Skip caption burn-in")
    args = p.parse_args()

    env = load_env()
    if not env.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY missing (used for gpt-4o-mini script draft)",
              file=sys.stderr); return 2
    # Provider-specific validation
    if args.voice_provider == "eleven":
        if not env.get("ELEVENLABS_API_KEY"):
            print("ERROR: --voice-provider=eleven needs ELEVENLABS_API_KEY",
                  file=sys.stderr); return 2
        voice_id = args.voice_id or env.get("ELEVEN_VOICE_ID", "")
        if not voice_id:
            print("ERROR: --voice-provider=eleven needs --voice-id or ELEVEN_VOICE_ID",
                  file=sys.stderr); return 2
    elif args.voice_provider == "openai":
        voice_id = args.voice_id or "onyx"   # default OpenAI voice
    else:  # mac-say
        voice_id = args.voice_id or "Daniel"

    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.out:
        out_path = Path(args.out)
    else:
        existing = sorted(DEFAULT_OUT_DIR.glob("wisdom-*.mp4"))
        nums = [int(re.search(r"wisdom-(\d+)", f.stem).group(1))
                for f in existing if re.search(r"wisdom-(\d+)", f.stem)]
        n = (max(nums) + 1) if nums else 1
        out_path = DEFAULT_OUT_DIR / f"wisdom-{n:03d}.mp4"
    work = out_path.parent / f"{out_path.stem}-work"
    work.mkdir(exist_ok=True)

    # Cache invalidation (if requested)
    use_cache = not args.no_cache
    # Stage output paths — the cache layer reads these to know what
    # `.cache-key` sidecars to remove when --from-cache is invoked.
    stage_outputs = {
        "script":   work / "plan.json",
        "art":      work / "art",                    # dir, not file
        "tts":      work / "voice.mp3",
        "video":    work / "video-raw.mp4",
        "captions": work / "video-captioned.mp4",
        "final":    out_path,
    }
    if args.from_cache and use_cache:
        _cache.invalidate_from(args.from_cache, stage_outputs)

    print(f"📍 idea: {args.idea[:80]}", file=sys.stderr)
    print(f"📤 out: {out_path}", file=sys.stderr)
    if use_cache:
        print(f"💾 cache: enabled (work dir: {work.name})", file=sys.stderr)

    # 1. Context
    print("\n[1/6] Gathering context…", file=sys.stderr)
    ctx_dir = Path(args.context).expanduser() if args.context else None
    blog_corpus = Path(args.blog_corpus).expanduser() if args.blog_corpus else None
    context = gather_context(args.idea, ctx_dir, blog_corpus=blog_corpus,
                             strict=args.strict)
    print(f"  pulled {len(context)} chars total"
          f"{' [strict]' if args.strict else ''}", file=sys.stderr)

    # 2. Script + cues (cached — gpt-4o-mini at temperature=0.7 is
    # non-deterministic, so without caching every retry produces a different
    # script + cues, defeating downstream caches. We cache the LLM output
    # keyed by the inputs that should determine it.)
    print("\n[2/6] Drafting script (gpt-4o-mini)…", file=sys.stderr)
    script_cache_path = work / "plan.json"
    script_key = _cache.hash_inputs("script", args.idea, context,
                                    args.style, args.strict, args.persona)
    if use_cache and _cache.cache_check(script_cache_path, script_key):
        plan = json.loads(script_cache_path.read_text())
        print(f"  💾 cache hit — script '{plan.get('title','?')[:40]}' reused",
              file=sys.stderr)
    else:
        plan = draft_script(args.idea, context, env["OPENAI_API_KEY"],
                            style=args.style, strict=args.strict,
                            persona=args.persona)
        if use_cache:
            script_cache_path.write_text(json.dumps(plan, indent=2))
            _cache.cache_save(script_cache_path, script_key)
    title = plan.get("title", "Wisdom")
    script = plan.get("script", "")
    cues   = plan.get("visual_cues", [])
    word_count = len(script.split())
    print(f"  title: {title}", file=sys.stderr)
    print(f"  {word_count} words ({word_count/2.5:.0f} s @ 150wpm), {len(cues)} cues",
          file=sys.stderr)
    (out_path.with_suffix(".meta.json")).write_text(json.dumps(plan, indent=2))

    # ── --draft-only short-circuit: write HTML preview and stop ─────────
    if args.draft_only:
        preview_path = out_path.with_suffix(".preview.html")
        write_preview_html(plan, preview_path, args.idea,
                           args.voice_provider, voice_id)
        print(f"\n📄 preview: {preview_path}", file=sys.stderr)
        print(f"   open it, decide if it's worth rendering, then re-run "
              f"without --draft-only.", file=sys.stderr)
        print(preview_path)   # stdout for capture
        return 0

    # 3. Art (cached)
    print(f"\n[3/6] Fetching art for {len(cues)} cues…", file=sys.stderr)
    photo_dirs = [Path(p).expanduser() for p in (args.user_photos or [])]
    user_photos = _list_user_photos(photo_dirs)
    if user_photos:
        random.seed(hash(args.idea) & 0xFFFFFFFF)
        random.shuffle(user_photos)
        print(f"  found {len(user_photos)} user photo(s) — will mix in", file=sys.stderr)
    else:
        print(f"  no user photos provided — using art-only", file=sys.stderr)
    art_dir = work / "art"
    art_key = _cache.hash_inputs("art", cues, [str(p) for p in user_photos[:32]])
    if use_cache and _cache.cache_check_dir(art_dir, art_key):
        art_paths = sorted(art_dir.glob("composite-*.jpg"))
        print(f"  💾 cache hit — {len(art_paths)} composites reused", file=sys.stderr)
    else:
        art_paths = fetch_art_for_cues(cues, art_dir, user_photos=user_photos)
        if not art_paths:
            print("ERROR: no art could be fetched", file=sys.stderr); return 3
        if use_cache:
            _cache.cache_save_dir(art_dir, art_key)
        print(f"  ✓ {len(art_paths)} composite images built", file=sys.stderr)

    # 4. TTS (cached)
    print(f"\n[4/6] Rendering voice ({args.voice_provider}/{voice_id})…",
          file=sys.stderr)
    audio_path = work / "voice.mp3"
    tts_key = _cache.hash_inputs("tts", script, args.voice_provider, voice_id)
    if use_cache and _cache.cache_check(audio_path, tts_key):
        # Recompute duration via ffprobe (cheap)
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True,
        )
        duration = float(p.stdout.strip() or "0")
        print(f"  💾 cache hit — {duration:.1f} s audio reused", file=sys.stderr)
    else:
        duration = render_tts(script, args.voice_provider, voice_id, audio_path, env)
        if use_cache:
            _cache.cache_save(audio_path, tts_key)
        print(f"  ✓ {duration:.1f} s audio", file=sys.stderr)

    # 5. Compose video (cached)
    print(f"\n[5/6] Composing video {WIDTH}×{HEIGHT}@{duration:.0f} s…", file=sys.stderr)
    raw_video = work / "video-raw.mp4"
    end_card = Path(args.end_photo).expanduser() if args.end_photo else None
    video_key = _cache.hash_inputs("video", art_key, tts_key, str(end_card) if end_card else "")
    if use_cache and _cache.cache_check(raw_video, video_key):
        print(f"  💾 cache hit — raw video reused", file=sys.stderr)
    else:
        build_video(art_paths, audio_path, duration, end_card, raw_video, title=title)
        if use_cache:
            _cache.cache_save(raw_video, video_key)

    # 5b. Captions (cached)
    if args.no_captions:
        intermediate = raw_video
    else:
        caption_chunks = split_script_for_captions(script, len(art_paths))
        intermediate = work / "video-captioned.mp4"
        cap_key = _cache.hash_inputs("captions", video_key, caption_chunks, duration)
        if use_cache and _cache.cache_check(intermediate, cap_key):
            print(f"  💾 cache hit — captioned video reused", file=sys.stderr)
        else:
            burn_captions(raw_video, intermediate, caption_chunks, duration)
            if use_cache:
                _cache.cache_save(intermediate, cap_key)

    # 5c. Final compress (cached)
    final_key = _cache.hash_inputs("final", intermediate, 1400, args.no_captions)
    if use_cache and _cache.cache_check(out_path, final_key):
        print(f"  💾 cache hit — final {out_path.stat().st_size//1024} KB reused",
              file=sys.stderr)
    else:
        target_kbps = 1400
        cmd_compress = [
            "ffmpeg", "-y", "-i", str(intermediate),
            "-c:v", "libx264", "-preset", "medium", "-crf", "26",
            "-maxrate", f"{target_kbps}k", "-bufsize", f"{target_kbps*2}k",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        r = subprocess.run(cmd_compress, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  [compress] failed; using uncompressed: {r.stderr[-300:]}",
                  file=sys.stderr)
            shutil.copy(intermediate, out_path)
        if use_cache:
            _cache.cache_save(out_path, final_key)
        print(f"  ✓ {out_path} ({out_path.stat().st_size // 1024} KB)", file=sys.stderr)

    # 6. Push
    if not args.no_push:
        print(f"\n[6/6] Pushing to Telegram…", file=sys.stderr)
        token_file = Path(env.get("TG_BOT_TOKEN_FILE") or DEFAULT_TG_TOKEN_FILE).expanduser()
        chats: list[int] = []
        if env.get("TG_DM_CHAT_ID"):
            try: chats.append(int(env["TG_DM_CHAT_ID"]))
            except ValueError: pass
        if env.get("TG_COUNCIL_CHAT_ID"):
            try: chats.append(int(env["TG_COUNCIL_CHAT_ID"]))
            except ValueError: pass
        cap = f"🎬 {title} ({duration:.0f}s)"
        push_to_telegram(out_path, cap, chats, token_file)

    print(f"\n✅ {out_path}", file=sys.stderr)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
