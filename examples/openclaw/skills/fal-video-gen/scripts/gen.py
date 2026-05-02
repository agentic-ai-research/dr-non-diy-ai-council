#!/usr/bin/env python3
"""
fal-video-gen — generate short videos via fal.ai.

Sister to fal-image-gen. Same env (FAL_KEY), same CLI shape, same poll-and-
download pattern. Models: wan-2.5 (default, cheap), kling-2, veo-3, sora-2.

Stdlib-only. Uses urllib + json. No fal-client dependency.

Usage:
    python3 gen.py --prompt "..." --duration 5 --aspect 16:9 --out clip.mp4
    python3 gen.py --prompt "..." --image ref.png --model kling-2 --out clip.mp4
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# --- Model registry (endpoints + cost/sec) -------------------------------------

MODELS: dict[str, dict[str, Any]] = {
    "wan-2.5": {
        "endpoint":     "fal-ai/wan-25-preview/text-to-video",
        "i2v_endpoint": "fal-ai/wan-25-preview/image-to-video",
        "cost_per_sec": 0.010,
        "max_duration": 5,
    },
    "kling-2": {
        "endpoint":     "fal-ai/kling-video/v2/master/text-to-video",
        "i2v_endpoint": "fal-ai/kling-video/v2/master/image-to-video",
        "cost_per_sec": 0.040,
        "max_duration": 10,
    },
    "veo-3": {
        "endpoint":     "fal-ai/veo3/text-to-video",
        "i2v_endpoint": "fal-ai/veo3/image-to-video",
        "cost_per_sec": 0.100,
        "max_duration": 8,
    },
    "sora-2": {
        "endpoint":     "fal-ai/sora-2/text-to-video",
        "i2v_endpoint": "fal-ai/sora-2/image-to-video",
        "cost_per_sec": 0.080,
        "max_duration": 8,
    },
}

ASPECT_TO_RESOLUTION = {
    "16:9": "1280x720",
    "9:16": "720x1280",
    "1:1":  "1024x1024",
}

DEFAULT_MAX_COST = float(os.environ.get("MAX_COST", "0.50"))
FAL_QUEUE = "https://queue.fal.run"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [fal-video-gen] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("fal-video-gen")


# --- HTTP helpers --------------------------------------------------------------

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


def _download_to(url: str, dest: Path, timeout: int = 240) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


def _image_to_data_uri(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


# --- fal.ai queue helpers ------------------------------------------------------

def _submit(endpoint: str, body: dict[str, Any], headers: dict[str, str]) -> str:
    """Submit a job to fal.ai's queue, return the request_id."""
    url = f"{FAL_QUEUE}/{endpoint}"
    log.info("submit → %s", url)
    resp = _http_post_json(url, body, headers, timeout=60)
    rid = resp.get("request_id")
    if not rid:
        log.error("no request_id in submit response: %s", json.dumps(resp)[:300])
        sys.exit(1)
    return rid


def _wait(endpoint: str, rid: str, headers: dict[str, str],
          deadline_s: int = 600) -> dict[str, Any]:
    """Poll the queue until the job completes (or times out)."""
    status_url = f"{FAL_QUEUE}/{endpoint}/requests/{rid}/status"
    result_url = f"{FAL_QUEUE}/{endpoint}/requests/{rid}"
    deadline = time.time() + deadline_s
    last_log = 0.0
    while time.time() < deadline:
        time.sleep(3)
        s = _http_get_json(status_url, headers)
        status = s.get("status")
        if status == "COMPLETED":
            return _http_get_json(result_url, headers)
        if status in ("FAILED", "CANCELLED"):
            log.error("job %s: %s", status, json.dumps(s)[:300])
            sys.exit(1)
        # Throttle log lines to once every 15s
        if time.time() - last_log > 15:
            log.info("status=%s; polling…", status)
            last_log = time.time()
    log.error("timeout after %ds waiting for request %s", deadline_s, rid)
    sys.exit(1)


# --- Generate ------------------------------------------------------------------

def generate(model: str, prompt: str, duration: int, aspect: str,
             image: Path | None, seed: int, out: Path) -> None:
    api_key = os.environ.get("FAL_KEY")
    if not api_key:
        log.error("FAL_KEY not set; export it from your fal.ai dashboard.")
        sys.exit(1)

    spec = MODELS[model]
    duration = min(duration, spec["max_duration"])
    headers = {"Authorization": f"Key {api_key}"}

    body: dict[str, Any] = {
        "prompt":          prompt,
        "duration":        duration,
        "resolution":      ASPECT_TO_RESOLUTION.get(aspect, "1280x720"),
        "aspect_ratio":    aspect,
        "seed":             seed,
    }

    endpoint = spec["endpoint"]
    if image is not None:
        body["image_url"] = _image_to_data_uri(image)
        endpoint = spec["i2v_endpoint"]

    rid = _submit(endpoint, body, headers)
    log.info("queued request_id=%s; waiting for completion…", rid)
    result = _wait(endpoint, rid, headers)

    # The result shape varies slightly across fal models; tolerate both common shapes.
    video = result.get("video") or {}
    video_url = video.get("url") if isinstance(video, dict) else None
    if not video_url:
        # Some models return a list under "videos"
        videos = result.get("videos") or []
        if videos and isinstance(videos[0], dict):
            video_url = videos[0].get("url")
    if not video_url:
        log.error("no video url in completed response: %s",
                  json.dumps(result)[:400])
        sys.exit(1)

    log.info("download → %s", out)
    _download_to(video_url, out)


# --- Cost guard ----------------------------------------------------------------

def _cost_guard(model: str, duration: int, max_cost: float, override: bool) -> None:
    rate = MODELS[model]["cost_per_sec"]
    est = rate * duration
    if est > max_cost and not override:
        log.error("cost guard: model=%s duration=%ds estimated=$%.4f exceeds $%.2f. "
                  "Pass --no-cost-guard to override.",
                  model, duration, est, max_cost)
        sys.exit(2)
    log.info("cost estimate: $%.4f (cap $%.2f)", est, max_cost)


# --- Main ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="fal-video-gen")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--duration", type=int, default=5,
                        help="Seconds; capped per-model")
    parser.add_argument("--aspect", choices=list(ASPECT_TO_RESOLUTION.keys()),
                        default="16:9")
    parser.add_argument("--out", required=True, help="Output MP4 path")
    parser.add_argument("--model", choices=list(MODELS.keys()),
                        default="wan-2.5")
    parser.add_argument("--image", default=None,
                        help="Path to a reference image for image-to-video")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-cost-guard", action="store_true")
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else random.randint(1, 2**31 - 1)
    out = Path(args.out).expanduser()
    image = Path(args.image).expanduser() if args.image else None
    if image is not None and not image.exists():
        log.error("--image path does not exist: %s", image)
        return 1

    _cost_guard(args.model, args.duration, DEFAULT_MAX_COST, args.no_cost_guard)

    try:
        generate(args.model, args.prompt, args.duration, args.aspect,
                 image, seed, out)
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
