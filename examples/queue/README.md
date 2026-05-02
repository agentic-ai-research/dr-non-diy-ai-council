# Queue — reference implementation

The runnable proof of [docs/queue.md](../../docs/queue.md). Stdlib-only, file-based, single-Mac. Drop into `~/.council/lib/queue.py` and `import queue` from any council bot's harness — or use it as a CLI for inspection and recovery.

## Setup

1. `~/.council/queue/` will be created on first `enqueue()` — no manual setup needed.
2. The queue uses `$COUNCIL_DIR` (default `~/.council`); override per-bot via env var if you want a sandbox.
3. No daemon. The queue is data; the bots are the workers.

## The 3-second ACK contract — Tenet's harness sketch

```python
import queue

def on_inbound(message):
    payload = {"text": message.text, "from": message.from_user.first_name,
               "telegram_msg_id": message.message_id}
    priority = parse_priority(message.text) or "normal"   # urgent / high / normal / low

    info = queue.enqueue(payload, priority=priority)
    # ACK in council transcript IMMEDIATELY (rule: within 3 s)
    transcript.append(
        f"ACK: {info['task_id']} [state={info['state']} "
        f"depth={info['depth']} your-position=#{info['position']} "
        f"priority={info['priority']}]"
    )
    # Now route — finish current first, or fan-out the new one in parallel.
```

The ACK happens before any LLM call, before any FAN-OUT, before any classification deeper than parsing the priority tag. Latency budget: ~50 ms in practice (file write + transcript append).

## Worker loop sketch (any bot)

```python
import queue, time

BOT_ID = "tenet"  # from $COUNCIL_BOT_NAME

while True:
    task = queue.claim(BOT_ID)
    if task is None:
        time.sleep(1)
        continue
    queue.start(task["task_id"], BOT_ID)
    try:
        result = do_the_work(task["payload"])      # the bot's actual logic
        queue.heartbeat(task["task_id"], BOT_ID)   # call periodically for long work
        queue.complete(task["task_id"], result_ref=result.get("ref"))
    except RetryableError as e:
        queue.fail(task["task_id"], str(e), retry=True)
    except FatalError as e:
        queue.fail(task["task_id"], str(e), retry=False)
```

## Stale-claim recovery (cron)

A claimed task that never starts, or an in-flight task whose heartbeat lapses past 30 s, is reclaimable. Run periodically:

```bash
*/1 * * * * /usr/bin/python3 -c "import queue; print(queue.recover_stale_claims())" \
            >> ~/.council/queue/recovery.log 2>&1
```

Recovery is idempotent and safe to run every minute.

## CLI inspector

The script is also runnable as `python -m queue ...`:

| Command | What it does |
|---|---|
| `python -m queue list` | Pending tasks, in priority + age order, with positions. |
| `python -m queue tail [N]` | Last N (default 20) state transitions from `index.jsonl`. |
| `python -m queue dead` | Tasks in the dead-letter queue, with last-failure reasons. |
| `python -m queue position <task_id>` | Where a task is in the pending queue. |
| `python -m queue revive <task_id>` | Pull a task back from DLQ to `pending/`, retry budget reset. |

Aliases on your shell help:

```bash
alias qls='python -m queue list'
alias qtail='python -m queue tail'
alias qdead='python -m queue dead'
```

## Dry run

Stdlib-only, so this works without any setup:

```python
import os
os.environ["COUNCIL_DIR"] = "/tmp/test-council"
import queue

q1 = queue.enqueue({"text": "draft Friday weekly", "from": "Dr Non"}, priority="high")
q2 = queue.enqueue({"text": "should I take BKK contract?", "from": "Dr Non"})
q3 = queue.enqueue({"text": "rebook flight", "from": "Dr Non"}, priority="urgent")

assert queue.peek(5)[0]["task_id"] == q3["task_id"]   # urgent first
print(queue.peek(5))
```

## Tunables

| Env / constant | Default | Effect |
|---|---|---|
| `COUNCIL_DIR` | `~/.council` | Root directory for queue + transcript + everything. |
| `DEFAULT_RETRIES` | `3` | Retry budget before a task goes to DLQ. |
| `RETRY_BACKOFFS` | `[30, 120, 300]` | Backoff (seconds) after the 1st, 2nd, 3rd failure. |
| `HEARTBEAT_TIMEOUT` | `30` | Seconds before a stale `CLAIMED` / `IN-FLIGHT` is reclaimable. |

## Operational notes

- **Concurrency**: The atomic `os.rename()` between `pending/` and `claimed/<bot_id>/` is POSIX-atomic on the same filesystem. Two bots calling `claim()` at the same instant cannot both end up with the same task.
- **Idempotency**: `enqueue()` hashes the payload; the same payload twice returns the existing `task_id` and the existing position. Useful when the inbound is retried (e.g., a Telegram update arrives twice).
- **Crash safety**: `_write_atomic()` writes to `<file>.tmp` then `replace()`s, so a crash mid-write never leaves a partial JSON.
- **Auditability**: `index.jsonl` is the chronological state log; `tail -f` it during work and watch the queue move.

## What this implementation does NOT do

- **No broker.** No Redis, no RabbitMQ, no NATS. File-based.
- **No cross-host claiming.** Single Mac, single queue dir.
- **No exactly-once delivery.** It's at-least-once with idempotency on payload hash. Same as everyone else.
- **No fancy backpressure** beyond depth reporting in the ACK. The harness layers (Tenet's prompt) handle the rejection logic when depth crosses the threshold.
- **No background daemon.** The queue is data on disk; bots poll it. If you want push semantics, that's a future M2 work item — but file-watching with `kqueue` or `fsevents` is the right addition then.
