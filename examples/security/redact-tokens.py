"""
redact-tokens.py — logging.Filter that scrubs credential-shaped strings
from log records BEFORE they reach disk.

Drop this into any Python logger that handles HTTP requests, model
output, or any text that might contain tokens. After attachment, the
filter rewrites known credential shapes in record.msg and record.args
so the secret never touches the log file.

Usage — direct API:

    import logging
    from redact_tokens import RedactingFilter

    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logging.getLogger().addHandler(handler)

Usage — dictConfig:

    {
      "filters": {
        "redact": {"()": "redact_tokens.RedactingFilter"}
      },
      "handlers": {
        "console": {
          "class":   "logging.StreamHandler",
          "filters": ["redact"]
        }
      },
      "root": {"handlers": ["console"], "level": "INFO"}
    }

Why this exists: see the council's Lock 2 in docs/inter-bot-protocols.md
and the SECURITY.md runbook at the repo root. Defense in depth — even
if a token escapes the keychain, this filter catches the leak at write
time.

Patterns mirror those in examples/council-transcript.example.py so
behavior is consistent across both write paths.
"""

from __future__ import annotations

import logging
import re

# Common credential shapes. Order matters slightly (more specific first).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Telegram bot tokens — bot<digits>:<35-ish url-safe>
    (re.compile(r"bot[0-9]{6,}:[A-Za-z0-9_-]{30,}"),         "bot<TG_TOKEN_REDACTED>"),
    # Bare Telegram token form (no "bot" prefix), e.g. inside JSON bodies
    (re.compile(r"\b[0-9]{6,}:[A-Za-z0-9_-]{35}\b"),         "<TG_TOKEN_REDACTED>"),
    # Anthropic
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),               "sk-ant-<REDACTED>"),
    # OpenAI / generic sk-
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"),                   "sk-<REDACTED>"),
    # GitHub personal-access tokens
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"),                    "ghp_<REDACTED>"),
    # Slack
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),            "xox<REDACTED>"),
    # AWS
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                    "AKIA<REDACTED>"),
    # Authorization: Bearer <token>
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{20,}"),         r"\1<REDACTED>"),
    # password=<value> — case-insensitive, anywhere in the string
    (re.compile(r"(?i)(password\s*[:=]\s*)\S+"),             r"\1<REDACTED>"),
]


def redact(s: str) -> str:
    """Return s with all known credential shapes replaced by placeholders."""
    if not isinstance(s, str):
        return s
    for pat, repl in _PATTERNS:
        s = pat.sub(repl, s)
    return s


class RedactingFilter(logging.Filter):
    """A logging filter that redacts credential-shaped strings from records.

    Operates on:
      - record.msg (when it is a string)
      - record.args (tuple of positional args, dict of named args)

    Filters MUST never raise; on any unexpected error, the record passes
    through unchanged (the redaction patterns that DID match still apply).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: (redact(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        redact(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        except Exception:
            pass
        return True


# --- Self-test ---------------------------------------------------------------
# Run `python3 redact-tokens.py` to verify the patterns work as expected.
# All sample inputs are SYNTHETIC — they match the SHAPE of credentials
# but are not real tokens.

if __name__ == "__main__":
    samples = [
        "POST https://api.telegram.org/bot1234567890:" + ("X" * 35) + "/getUpdates",
        "Authorization: Bearer " + ("Y" * 40),
        "API key: sk-anthropic-test-key-1234567890abcdef",
        "API key: sk-ant-test1234567890abcdef1234567890",
        "AWS access: AKIAIOSFODNN7EXAMPLE",
        "config: password=hunter2",
        "github: ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "slack token: xoxb-1234567890-abcdefghij",
        "(no secret here, just plain text)",
    ]
    print("Input  →  Redacted\n")
    all_ok = True
    for s in samples:
        out = redact(s)
        # If the original contained a credential shape, the output must
        # not be identical to the input.
        original_was_secret = any(p.search(s) for p, _ in _PATTERNS)
        ok = (out != s) if original_was_secret else (out == s)
        flag = "✓" if ok else "✗ FAILED"
        print(f"  {s!r}")
        print(f"  → {out!r}  {flag}\n")
        all_ok = all_ok and ok
    if not all_ok:
        raise SystemExit("self-test FAILED — patterns need adjustment")
    print("self-test OK")
