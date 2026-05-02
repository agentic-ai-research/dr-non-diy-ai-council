"""
queue.py — file-based task queue with ACK contract for the council.

Implements the spec in docs/queue.md. Stdlib-only. Single-Mac. The queue
is the council's main feature — every inbound from Dr Non gets an ACK
within 3 seconds before any other action.

State machine:
    RECEIVED -> QUEUED -> CLAIMED -> IN-FLIGHT -> DONE
                            |           |
                            |           +-> BLOCKED-ON-BENCH -> IN-FLIGHT (resume)
                            |           +-> FAILED -> retry? -> QUEUED  |  -> dead/
                            +-> (visibility timeout) -> QUEUED  (reclaim)
                                                         REVOKED  (manual kill)

File layout under $COUNCIL_DIR/queue/:
    index.jsonl                       - append-only state log
    pending/<task_id>.json            - waiting for a worker
    claimed/<bot_id>/<task_id>.json   - claimed; not yet started
    in-flight/<task_id>.json          - actively being processed (heartbeat)
    done/<task_id>.json               - completed
    dead/<task_id>.json               - failed past retry budget

Usage as a library:
    from queue import enqueue, claim, start, complete, fail, peek, position
    task_id = enqueue({"text": "rebook flight", "from": "Dr Non"}, priority="urgent")

Usage as a CLI:
    python -m queue list
    python -m queue tail
    python -m queue dead
    python -m queue position <task_id>
    python -m queue revive <task_id>
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# --- Config ------------------------------------------------------------------

COUNCIL_DIR = Path(os.environ.get("COUNCIL_DIR", str(Path.home() / ".council")))
QUEUE_DIR   = COUNCIL_DIR / "queue"
INDEX_PATH  = QUEUE_DIR / "index.jsonl"

PENDING_DIR   = QUEUE_DIR / "pending"
CLAIMED_DIR   = QUEUE_DIR / "claimed"
IN_FLIGHT_DIR = QUEUE_DIR / "in-flight"
DONE_DIR      = QUEUE_DIR / "done"
DEAD_DIR      = QUEUE_DIR / "dead"

PRIORITIES        = ("urgent", "high", "normal", "low")
DEFAULT_PRIORITY  = "normal"
DEFAULT_RETRIES   = 3
RETRY_BACKOFFS    = [30, 120, 300]   # seconds
HEARTBEAT_TIMEOUT = 30                # seconds before a CLAIMED task is reclaimable
SLUG_RE           = re.compile(r"[a-z0-9-]+")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [queue] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("queue")


# --- Helpers -----------------------------------------------------------------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _slugify(text: str, max_len: int = 32) -> str:
    """Lowercase, hyphen-separated, alnum + dash, truncated."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "task").lower()).strip("-")
    return (slug or "task")[:max_len]


def _payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash of payload for idempotency."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def _ensure_dirs() -> None:
    for d in (PENDING_DIR, CLAIMED_DIR, IN_FLIGHT_DIR, DONE_DIR, DEAD_DIR, QUEUE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _append_index(record: dict[str, Any]) -> None:
    """Append a state-transition record to index.jsonl. Best-effort, never raises."""
    line = json.dumps(record, ensure_ascii=False)
    try:
        _ensure_dirs()
        with INDEX_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        log.error("index append failed: %s", e)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to a temp file, then rename. Atomic on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _priority_rank(p: str) -> int:
    try:
        return PRIORITIES.index(p)
    except ValueError:
        return PRIORITIES.index(DEFAULT_PRIORITY)


# --- Public API --------------------------------------------------------------

def enqueue(payload: dict[str, Any], priority: str = DEFAULT_PRIORITY,
            slug_hint: Optional[str] = None) -> dict[str, Any]:
    """Enqueue a task. Returns ACK info (task_id, position, depth, est_wait)."""
    _ensure_dirs()
    if priority not in PRIORITIES:
        priority = DEFAULT_PRIORITY

    payload_hash = _payload_hash(payload)
    # Idempotency: same payload twice = same task_id
    for existing in PENDING_DIR.glob("*.json"):
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
            if data.get("payload_hash") == payload_hash:
                log.info("idempotent enqueue: returning existing %s", data["task_id"])
                return {"task_id": data["task_id"], "state": "queued",
                        "position": _position_in_pending(data["task_id"]),
                        "depth": _depth(), "idempotent": True}
        except (OSError, json.JSONDecodeError):
            continue

    epoch = int(time.time())
    slug = _slugify(slug_hint or payload.get("slug") or
                    (payload.get("text") or "task")[:32])
    task_id = f"{slug}-{epoch}"

    record = {
        "task_id":      task_id,
        "payload":      payload,
        "payload_hash": payload_hash,
        "priority":     priority,
        "retries":      0,
        "received_ts":  _now_iso(),
    }
    _write_atomic(PENDING_DIR / f"{task_id}.json", record)

    _append_index({
        "ts": _now_iso(), "task_id": task_id, "from": "received", "to": "queued",
        "priority": priority, "actor": payload.get("from", "unknown"),
        "position": _position_in_pending(task_id), "depth": _depth(),
    })

    log.info("enqueued %s (priority=%s)", task_id, priority)
    return {
        "task_id":  task_id,
        "state":    "queued",
        "position": _position_in_pending(task_id),
        "depth":    _depth(),
        "priority": priority,
    }


def claim(bot_id: str) -> Optional[dict[str, Any]]:
    """Atomically claim the highest-priority oldest pending task.

    Returns the task dict, or None if nothing pending.
    """
    _ensure_dirs()
    candidates = sorted(
        PENDING_DIR.glob("*.json"),
        key=lambda p: (
            _priority_rank((_safe_load(p) or {}).get("priority", DEFAULT_PRIORITY)),
            p.stat().st_mtime,
        ),
    )
    for src in candidates:
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        target_dir = CLAIMED_DIR / bot_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        try:
            os.rename(src, target)  # atomic on POSIX
        except OSError:
            continue   # someone else claimed it; try the next one
        data["claimed_by"] = bot_id
        data["claimed_ts"] = _now_iso()
        _write_atomic(target, data)
        _append_index({
            "ts": _now_iso(), "task_id": data["task_id"],
            "from": "queued", "to": "claimed",
            "actor": bot_id, "worker": bot_id,
        })
        log.info("%s claimed %s", bot_id, data["task_id"])
        return data
    return None


def start(task_id: str, bot_id: str) -> None:
    """Move a CLAIMED task to IN-FLIGHT and write a heartbeat."""
    src = CLAIMED_DIR / bot_id / f"{task_id}.json"
    if not src.exists():
        log.warning("start: no claimed task %s for %s", task_id, bot_id)
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("start: cannot read %s: %s", src, e)
        return
    target = IN_FLIGHT_DIR / f"{task_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data["started_ts"] = _now_iso()
    data["heartbeat_ts"] = _now_iso()
    _write_atomic(target, data)
    try:
        src.unlink()
    except OSError:
        pass
    _append_index({
        "ts": _now_iso(), "task_id": task_id,
        "from": "claimed", "to": "in-flight", "actor": bot_id,
    })


def heartbeat(task_id: str, bot_id: str) -> None:
    """Update the heartbeat timestamp on an in-flight task."""
    p = IN_FLIGHT_DIR / f"{task_id}.json"
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data["heartbeat_ts"] = _now_iso()
        _write_atomic(p, data)
    except (OSError, json.JSONDecodeError):
        pass


def complete(task_id: str, result_ref: Optional[str] = None) -> None:
    """Move IN-FLIGHT -> DONE."""
    src = IN_FLIGHT_DIR / f"{task_id}.json"
    if not src.exists():
        log.warning("complete: no in-flight task %s", task_id)
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["done_ts"] = _now_iso()
    if result_ref:
        data["result_ref"] = result_ref
    target = DONE_DIR / f"{task_id}.json"
    _write_atomic(target, data)
    try:
        src.unlink()
    except OSError:
        pass
    _append_index({
        "ts": _now_iso(), "task_id": task_id,
        "from": "in-flight", "to": "done", "actor": data.get("claimed_by", "unknown"),
        "result_ref": result_ref,
    })


def fail(task_id: str, reason: str, retry: bool = True,
         max_retries: int = DEFAULT_RETRIES) -> None:
    """Handle a failure. Either retry-with-backoff or move to DLQ."""
    # Locate the task wherever it currently lives.
    candidate_paths = [
        IN_FLIGHT_DIR / f"{task_id}.json",
        *(CLAIMED_DIR.glob(f"*/{task_id}.json")),
        PENDING_DIR  / f"{task_id}.json",
    ]
    src = next((p for p in candidate_paths if p.exists()), None)
    if src is None:
        log.warning("fail: task %s not found in any state dir", task_id)
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data.setdefault("failures", []).append({
        "ts": _now_iso(), "reason": reason,
    })
    retries_used = data.get("retries", 0)
    if retry and retries_used < max_retries:
        # Back to pending with backoff annotation.
        data["retries"] = retries_used + 1
        backoff = RETRY_BACKOFFS[min(retries_used, len(RETRY_BACKOFFS) - 1)]
        data["retry_after_ts"] = (_dt.datetime.now(_dt.timezone.utc)
                                  + _dt.timedelta(seconds=backoff)).isoformat(timespec="seconds")
        target = PENDING_DIR / f"{task_id}.json"
        _write_atomic(target, data)
        try:
            if src != target:
                src.unlink()
        except OSError:
            pass
        _append_index({
            "ts": _now_iso(), "task_id": task_id,
            "from": "in-flight", "to": "queued", "actor": data.get("claimed_by", "unknown"),
            "reason": reason, "retry": data["retries"], "backoff_s": backoff,
        })
        log.info("retry %s (attempt %d/%d, backoff %ds)",
                 task_id, data["retries"], max_retries, backoff)
        return

    # DLQ.
    target = DEAD_DIR / f"{task_id}.json"
    data["dead_ts"] = _now_iso()
    _write_atomic(target, data)
    try:
        if src != target:
            src.unlink()
    except OSError:
        pass
    _append_index({
        "ts": _now_iso(), "task_id": task_id,
        "from": "in-flight", "to": "dead", "actor": data.get("claimed_by", "unknown"),
        "reason": reason,
    })
    log.error("DLQ %s after %d retries: %s", task_id, retries_used, reason)


def peek(n: int = 10) -> list[dict[str, Any]]:
    _ensure_dirs()
    files = sorted(
        PENDING_DIR.glob("*.json"),
        key=lambda p: (
            _priority_rank((_safe_load(p) or {}).get("priority", DEFAULT_PRIORITY)),
            p.stat().st_mtime,
        ),
    )[:n]
    return [_safe_load(p) for p in files if _safe_load(p) is not None]


def position(task_id: str) -> int:
    """Position in pending queue (1-indexed). Returns 0 if not pending."""
    return _position_in_pending(task_id)


def recover_stale_claims(timeout_s: int = HEARTBEAT_TIMEOUT) -> list[str]:
    """Reclaim CLAIMED tasks whose IN-FLIGHT heartbeat is stale (or never started).

    Returns the list of recovered task_ids.
    """
    recovered: list[str] = []
    now = _dt.datetime.now(_dt.timezone.utc)
    # Stale CLAIMED (no start)
    for src in CLAIMED_DIR.glob("*/*.json"):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            claimed_at = _dt.datetime.fromisoformat(data.get("claimed_ts", _now_iso()))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if (now - claimed_at).total_seconds() > timeout_s:
            target = PENDING_DIR / src.name
            _write_atomic(target, data)
            try:
                src.unlink()
            except OSError:
                pass
            _append_index({
                "ts": _now_iso(), "task_id": data["task_id"],
                "from": "claimed", "to": "queued", "actor": "queue-recovery",
                "reason": f"stale-claim (>{timeout_s}s)",
            })
            recovered.append(data["task_id"])
    # Stale IN-FLIGHT (heartbeat lost)
    for src in IN_FLIGHT_DIR.glob("*.json"):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            hb = _dt.datetime.fromisoformat(data.get("heartbeat_ts", _now_iso()))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if (now - hb).total_seconds() > timeout_s:
            target = PENDING_DIR / src.name
            _write_atomic(target, data)
            try:
                src.unlink()
            except OSError:
                pass
            _append_index({
                "ts": _now_iso(), "task_id": data["task_id"],
                "from": "in-flight", "to": "queued", "actor": "queue-recovery",
                "reason": f"stale-heartbeat (>{timeout_s}s)",
            })
            recovered.append(data["task_id"])
    return recovered


# --- Internal ----------------------------------------------------------------

def _safe_load(p: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _depth() -> int:
    return len(list(PENDING_DIR.glob("*.json")))


def _position_in_pending(task_id: str) -> int:
    files = sorted(
        PENDING_DIR.glob("*.json"),
        key=lambda p: (
            _priority_rank((_safe_load(p) or {}).get("priority", DEFAULT_PRIORITY)),
            p.stat().st_mtime,
        ),
    )
    for i, p in enumerate(files, start=1):
        if p.stem == task_id:
            return i
    return 0


# --- CLI ---------------------------------------------------------------------

def _cli_list() -> int:
    tasks = peek(100)
    if not tasks:
        print("(queue empty)")
        return 0
    print(f"{'POS':>3} {'PRIORITY':>8}  TASK_ID")
    for i, t in enumerate(tasks, start=1):
        print(f"{i:>3} {t.get('priority', '?'):>8}  {t.get('task_id', '?')}")
    return 0


def _cli_tail(n: int = 20) -> int:
    entries = _read_jsonl(INDEX_PATH)[-n:]
    for e in entries:
        print(f"{e.get('ts','?')}  {e.get('task_id','?')}  "
              f"{e.get('from','?')} -> {e.get('to','?')}  "
              f"({e.get('actor','?')})")
    return 0


def _cli_dead() -> int:
    files = sorted(DEAD_DIR.glob("*.json"))
    if not files:
        print("(no dead-letter tasks)")
        return 0
    for f in files:
        d = _safe_load(f) or {}
        last = (d.get("failures") or [{}])[-1].get("reason", "(no reason)")
        print(f"{d.get('task_id','?')}  retries={d.get('retries','?')}  last={last}")
    return 0


def _cli_position(task_id: str) -> int:
    pos = position(task_id)
    if pos == 0:
        print(f"{task_id}: not pending")
        return 1
    print(f"{task_id}: position #{pos} (depth {_depth()})")
    return 0


def _cli_revive(task_id: str) -> int:
    src = DEAD_DIR / f"{task_id}.json"
    if not src.exists():
        print(f"not in DLQ: {task_id}", file=sys.stderr)
        return 1
    data = _safe_load(src)
    if not data:
        return 1
    data["retries"] = 0
    data["failures"] = []
    target = PENDING_DIR / f"{task_id}.json"
    _write_atomic(target, data)
    src.unlink()
    _append_index({
        "ts": _now_iso(), "task_id": task_id,
        "from": "dead", "to": "queued", "actor": "manual-revive",
    })
    print(f"revived {task_id}")
    return 0


def _cli(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m queue {list|tail|dead|position <id>|revive <id>}",
              file=sys.stderr)
        return 2
    cmd, *rest = argv
    if cmd == "list":     return _cli_list()
    if cmd == "tail":     return _cli_tail(int(rest[0]) if rest else 20)
    if cmd == "dead":     return _cli_dead()
    if cmd == "position" and rest: return _cli_position(rest[0])
    if cmd == "revive"   and rest: return _cli_revive(rest[0])
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
