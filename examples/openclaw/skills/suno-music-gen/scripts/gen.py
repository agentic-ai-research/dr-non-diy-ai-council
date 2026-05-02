#!/usr/bin/env python3
"""
suno-music-gen — generate music from a text prompt via one of three backends.

Default backend is MusicGen on Replicate (free credits at signup; functionally
$0 for everyday use). Switchable to Suno (paid, vocals) or Stable Audio.

Stdlib-only. Uses urllib for HTTP, json for protocol, time for polling.

Usage:
    python3 gen.py --prompt "..." --duration 30 --out /path/to/song.mp3

Reads API token from env (REPLICATE_API_TOKEN, SUNO_API_KEY, or
STABILITY_API_KEY depending on backend).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# --- Backend pricing (rough; check provider for current rates) -----------------

BACKEND_COST_PER_SECOND = {
    "replicate-musicgen": 0.0023,    # ~$0.0023/sec on Replicate's MusicGen
    "suno":               0.005,     # rough; Suno's pricing is per-call but normalized here
    "stable-audio":       0.0,       # free tier covers reasonable usage
}

DEFAULT_MAX_COST = float(os.environ.get("MAX_COST", "0.50"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [suno-music-gen] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("suno-music-gen")


# --- HTTP helpers (stdlib) -----------------------------------------------------

def _http_post_json(url: str, body: dict[str, Any], headers: dict[str, str],
                    timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, headers: dict[str, str],
                   timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_to(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


# --- Backend: Replicate MusicGen -----------------------------------------------

REPLICATE_MUSICGEN_VERSION = "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"  # facebook/musicgen-stereo-large
REPLICATE_API = "https://api.replicate.com/v1"


def gen_replicate_musicgen(prompt: str, duration: int, out: Path,
                           seed: int) -> None:
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        log.error("REPLICATE_API_TOKEN not set; export it or use --backend.")
        sys.exit(1)

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type":  "application/json",
    }
    body = {
        "version": REPLICATE_MUSICGEN_VERSION,
        "input": {
            "prompt":          prompt,
            "duration":        min(duration, 30),  # Replicate cap
            "output_format":   "mp3",
            "normalization_strategy": "peak",
            "seed":            seed,
        },
    }
    log.info("starting Replicate MusicGen prediction (duration=%ds, seed=%d)…",
             duration, seed)
    pred = _http_post_json(f"{REPLICATE_API}/predictions", body, headers)
    pred_id = pred.get("id")
    if not pred_id:
        log.error("no prediction id in response: %s", json.dumps(pred)[:300])
        sys.exit(1)

    poll_url = f"{REPLICATE_API}/predictions/{pred_id}"
    deadline = time.time() + 300  # 5 min max
    while time.time() < deadline:
        time.sleep(3)
        status_resp = _http_get_json(poll_url, headers)
        status = status_resp.get("status")
        if status == "succeeded":
            output_url = status_resp.get("output")
            if isinstance(output_url, list):
                output_url = output_url[0] if output_url else None
            if not output_url:
                log.error("succeeded but no output url; full response: %s",
                          json.dumps(status_resp)[:300])
                sys.exit(1)
            log.info("download → %s", out)
            _download_to(output_url, out)
            return
        if status in ("failed", "canceled"):
            err = status_resp.get("error") or "(no error message)"
            log.error("prediction %s: %s", status, err)
            sys.exit(1)
        log.info("status=%s; polling…", status)

    log.error("timeout after 5 min waiting for prediction %s", pred_id)
    sys.exit(1)


# --- Backend: Suno (paid; vocal-quality) ---------------------------------------

def gen_suno(prompt: str, duration: int, out: Path, seed: int) -> None:
    token = os.environ.get("SUNO_API_KEY")
    if not token:
        log.error("SUNO_API_KEY not set; required for --backend suno.")
        sys.exit(1)
    # Suno's API surface varies by provider (sunoapi.org, suno-api proxies, etc.).
    # This is a placeholder shape; replace `endpoint` and request body with the
    # specific Suno-API-compatible endpoint your account is on.
    endpoint = os.environ.get("SUNO_API_ENDPOINT",
                              "https://api.sunoapi.org/api/v1/generate")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "prompt":     prompt,
        "make_instrumental": False,
        "wait_audio": True,
        "model":      "chirp-v3-5",
    }
    log.info("starting Suno generation…")
    result = _http_post_json(endpoint, body, headers, timeout=180)
    audio_url = (result.get("audio_url") or
                 (result.get("data") or [{}])[0].get("audio_url"))
    if not audio_url:
        log.error("no audio_url in Suno response: %s", json.dumps(result)[:300])
        sys.exit(1)
    log.info("download → %s", out)
    _download_to(audio_url, out)


# --- Backend: Stable Audio -----------------------------------------------------

def gen_stable_audio(prompt: str, duration: int, out: Path, seed: int) -> None:
    token = os.environ.get("STABILITY_API_KEY")
    if not token:
        log.error("STABILITY_API_KEY not set; required for --backend stable-audio.")
        sys.exit(1)
    endpoint = "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "audio/*",
    }
    # multipart/form-data is awkward with stdlib; we build it manually
    boundary = "----stableboundary7" + str(int(time.time()))
    parts = [
        f"--{boundary}",
        'Content-Disposition: form-data; name="prompt"',
        "",
        prompt,
        f"--{boundary}",
        'Content-Disposition: form-data; name="duration"',
        "",
        str(min(duration, 47)),  # Stable Audio cap
        f"--{boundary}",
        'Content-Disposition: form-data; name="seed"',
        "",
        str(seed),
        f"--{boundary}",
        'Content-Disposition: form-data; name="output_format"',
        "",
        "mp3",
        f"--{boundary}--",
        "",
    ]
    body = "\r\n".join(parts).encode("utf-8")
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body))
    req = urllib.request.Request(endpoint, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    out.parent.mkdir(parents=True, exist_ok=True)
    log.info("starting Stable Audio generation…")
    with urllib.request.urlopen(req, timeout=180) as resp, out.open("wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


# --- Cost guard ----------------------------------------------------------------

def _cost_guard(backend: str, duration: int, max_cost: float, override: bool) -> None:
    rate = BACKEND_COST_PER_SECOND.get(backend, 0.0)
    est = rate * duration
    if est > max_cost and not override:
        log.error("cost guard: backend=%s duration=%ds estimated=$%.4f exceeds $%.2f. "
                  "Pass --no-cost-guard to override.",
                  backend, duration, est, max_cost)
        sys.exit(2)
    if rate > 0:
        log.info("cost estimate: $%.4f (cap $%.2f)", est, max_cost)


# --- Main ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="suno-music-gen")
    parser.add_argument("--prompt", required=True,
                        help="Text description of the music")
    parser.add_argument("--duration", type=int, default=30,
                        help="Seconds; capped per-backend (Replicate 30, Stable 47)")
    parser.add_argument("--out", required=True, help="Output MP3 path")
    parser.add_argument("--backend",
                        choices=list(BACKEND_COST_PER_SECOND.keys()),
                        default="replicate-musicgen")
    parser.add_argument("--seed", type=int, default=None,
                        help="Reproducibility seed; random if omitted")
    parser.add_argument("--no-cost-guard", action="store_true",
                        help="Skip the cost-cap check")
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else random.randint(1, 2**31 - 1)
    out = Path(args.out).expanduser()
    _cost_guard(args.backend, args.duration, DEFAULT_MAX_COST, args.no_cost_guard)

    try:
        if args.backend == "replicate-musicgen":
            gen_replicate_musicgen(args.prompt, args.duration, out, seed)
        elif args.backend == "suno":
            gen_suno(args.prompt, args.duration, out, seed)
        elif args.backend == "stable-audio":
            gen_stable_audio(args.prompt, args.duration, out, seed)
        else:
            log.error("unknown backend: %s", args.backend)
            return 2
    except urllib.error.HTTPError as e:
        log.error("HTTP %d: %s", e.code, e.read()[:300].decode("utf-8", "replace"))
        return 1
    except urllib.error.URLError as e:
        log.error("URL error: %s", e)
        return 1

    if not out.exists() or out.stat().st_size == 0:
        log.error("output file missing or empty: %s", out)
        return 1
    log.info("✓ wrote %s (%d bytes)", out, out.stat().st_size)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
