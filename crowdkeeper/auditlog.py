import json
import os
import re
from datetime import datetime, timezone

SENSITIVE = {"password", "secret", "token"}


def record(path, action, **details):
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "action": action,
             **{k: v for k, v in details.items() if k not in SENSITIVE}}
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
