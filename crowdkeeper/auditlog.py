import json
from datetime import datetime, timezone

SENSITIVE = {"password", "secret", "token"}


def record(path, action, **details):
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "action": action,
             **{k: v for k, v in details.items() if k not in SENSITIVE}}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry
