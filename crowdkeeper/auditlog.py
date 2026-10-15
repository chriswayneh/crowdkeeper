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
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "action": action,
             **{k: v for k, v in fields.items() if k not in SENSITIVE},
             "detail": {k: v for k, v in (detail or {}).items() if k not in SENSITIVE}}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def safe_error(exc):
    """Error text for the log: exception type and message, with secrets scrubbed."""
    msg = f"{type(exc).__name__}: {exc}"
    pw = os.environ.get("CROWD_APP_PASSWORD")
    if pw:
        msg = msg.replace(pw, "***")
    msg = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", msg)  # credentials embedded in URLs
    return msg[:500]
