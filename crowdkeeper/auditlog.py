import json
import os
import re
from datetime import datetime, timezone

SENSITIVE = {"password", "secret", "token"}
RESERVED = {"ts", "event", "action", "seq", "run_id", "detail"}


def record(path, event, action, detail=None, **fields):
    """Append one JSON line. `event` is intent|applied|failed; the change's own keys go
    under a nested "detail" object so they can never overwrite top-level fields."""
    bad = (RESERVED - {"seq", "run_id"}) & fields.keys()
    if bad:
        raise ValueError(f"reserved audit-log field name(s): {', '.join(sorted(bad))}")
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "action": action,
        **{k: v for k, v in fields.items() if k not in SENSITIVE},
        "detail": {k: v for k, v in (detail or {}).items() if k not in SENSITIVE},
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def safe_error(exc):
    """Error text for the log: exception type and message, with secrets scrubbed."""
    return scrub(f"{type(exc).__name__}: {exc}")


MIN_SUBSTRING_MASK = 8


def scrub(msg):
    """Mask the app password and URL-embedded credentials in any text shown or logged.

    A password of 8+ characters is masked wherever it appears (substring). A shorter one is
    masked only where it stands alone as a token, so e.g. a password "us" does not turn
    "/rest/usermanagement" into "/rest/***ermanagement" while "password us rejected" still
    becomes "password *** rejected". Only letters/digits count as word characters, so a short
    password next to punctuation ("pw1.", "pw1-x", "_pw1_") is still masked.
    URL credentials are always masked."""
    msg = str(msg)
    pw = os.environ.get("CROWD_APP_PASSWORD")
    if pw and len(pw) >= MIN_SUBSTRING_MASK:
        msg = msg.replace(pw, "***")
    elif pw:
        msg = re.sub(r"(?<![A-Za-z0-9])" + re.escape(pw) + r"(?![A-Za-z0-9])", "***", msg)
    msg = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", msg)  # credentials embedded in URLs
    return msg[:500]
