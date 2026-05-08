"""Stage cache for tiktok-wisdom — content-hashed, idempotent re-runs.

Each pipeline stage writes one or more output files to the work directory.
We pair each output with a sidecar `.cache-key` file containing a hash of
the stage's INPUTS. On re-run, if the key matches, we skip the stage and
return the cached output.

Failure recovery: TTS dies at minute 2? Re-run the same command. Stages
1-3 (context, script, art) hit cache and skip. Stage 4 (TTS) runs fresh.
No more re-fetching art every time anything later in the pipeline blows up.

Stage IDs (in pipeline order):
  context | script | art | tts | video | captions | final

`--from-cache <stage>` invalidates that stage and everything downstream,
forcing re-run. `--no-cache` disables caching entirely.
"""
from __future__ import annotations

import hashlib, json, sys
from pathlib import Path

STAGES_IN_ORDER = ("context", "script", "art", "tts", "video", "captions", "final")


def hash_inputs(*parts) -> str:
    """Stable SHA-256 of the inputs. Strings/bytes/numbers/dicts/lists work.
    File Path objects are hashed by content (small files) or by
    (mtime, size, path) for fast hashing of large media.
    """
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, Path):
            if part.exists() and part.is_file():
                if part.stat().st_size < 256 * 1024:
                    h.update(part.read_bytes())
                else:
                    s = part.stat()
                    h.update(f"{part}:{s.st_mtime}:{s.st_size}".encode())
            else:
                h.update(f"{part}:absent".encode())
        elif isinstance(part, (dict, list)):
            h.update(json.dumps(part, sort_keys=True, default=str).encode())
        elif isinstance(part, bytes):
            h.update(part)
        else:
            h.update(str(part).encode())
        h.update(b"|")
    return h.hexdigest()[:16]


def _key_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".cache-key")


def cache_check(output_path: Path, key: str) -> bool:
    """Return True iff cached output exists AND its key matches."""
    kp = _key_path(output_path)
    if not output_path.exists() or not kp.exists():
        return False
    try:
        return kp.read_text().strip() == key
    except Exception:
        return False


def cache_save(output_path: Path, key: str) -> None:
    """Write the input-hash sidecar next to the output."""
    _key_path(output_path).write_text(key)


def cache_check_dir(out_dir: Path, key: str) -> bool:
    """For multi-output stages (e.g. art fetch produces N composites).
    The dir gets one `.cache-key` file at the top level."""
    kp = out_dir / ".cache-key"
    if not out_dir.exists() or not kp.exists():
        return False
    try:
        return kp.read_text().strip() == key
    except Exception:
        return False


def cache_save_dir(out_dir: Path, key: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".cache-key").write_text(key)


def invalidate_from(stage: str, stage_outputs: dict) -> None:
    """Delete cache keys for `stage` and all downstream stages, forcing
    re-run. Output files themselves are left in place — they'll be
    overwritten when stages re-execute.

    `stage_outputs` is a {stage_name: Path} dict — the canonical output
    file (or dir) for each stage. The caller (build.py) owns the path
    convention; this function only walks the dict and removes the
    corresponding sidecar `.cache-key` file (or dir-level `.cache-key`)
    for `stage` and every later stage in STAGES_IN_ORDER.
    """
    if stage not in STAGES_IN_ORDER:
        raise ValueError(f"unknown stage {stage!r}; choose from {STAGES_IN_ORDER}")
    start = STAGES_IN_ORDER.index(stage)
    targets = [s for s in STAGES_IN_ORDER[start:] if s in stage_outputs]
    print(f"  [cache] invalidating: {', '.join(targets)}", file=sys.stderr)
    for s in targets:
        out = stage_outputs.get(s)
        if out is None:
            continue
        if out.is_dir():
            (out / ".cache-key").unlink(missing_ok=True)
        else:
            _key_path(out).unlink(missing_ok=True)
