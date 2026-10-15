import sys
import csv
import io
import json
from datetime import datetime, timezone

from . import auditlog


def audit(directory, days=90, now=None):
    now = now or datetime.now(timezone.utc)
    users, groups = directory.users(), directory.groups()
    findings = []
    for u in users:
        if u.active and (u.last_login is None or (now - u.last_login).days >= days):
            seen = "never" if u.last_login is None else f"{(now - u.last_login).days}d ago"
            findings.append({"type": "inactive", "subject": u.name,
                             "detail": f"last login {seen}", "fix": "deactivate"})
        if u.active and not u.groups:
            findings.append({"type": "no-groups", "subject": u.name,
                             "detail": "active user in no groups", "fix": "review"})
        if not u.active and u.groups:
            findings.append({"type": "disabled-in-groups", "subject": u.name,
                             "detail": "disabled but in: " + ", ".join(u.groups),
                             "fix": "strip-groups", "groups": list(u.groups)})
    used = {g for u in users for g in u.groups}
    for g in groups:
        if g not in used:
            findings.append({"type": "empty-group", "subject": g,
                             "detail": "group has no members", "fix": "review"})
    return findings


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(v):
    """Neutralise spreadsheet formula injection (CWE-1236) in CSV cells."""
    v = "" if v is None else str(v)
    return "'" + v if v.startswith(_FORMULA) else v


def md_safe(v):
    """Escape characters that would break Markdown tables/code spans."""
    return str(v).replace("\\", "\\\\").replace("|", "\\|").replace("`", "'").replace("\n", " ")


def fmt(rows, cols, out="table"):
    if out == "json":
        return json.dumps(rows, indent=2, default=str)
    if out == "csv":
        b = io.StringIO()
        w = csv.DictWriter(b, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows({c: csv_safe(r.get(c, "")) for c in cols} for r in rows)
        return b.getvalue().rstrip("\n")
    if not rows:
        return "(nothing found)"
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols]
    line = lambda vals: "  ".join(str(v).ljust(w) for v, w in zip(vals, widths)).rstrip()
    return "\n".join([line(cols), line("-" * w for w in widths)] +
                     [line(r.get(c, "") for c in cols) for r in rows])


def export_groups(directory):
    m = {g: [] for g in directory.groups()}
    for u in directory.users():
        for g in u.groups:
            m.setdefault(g, []).append(u.name)
    return {"groups": {g: sorted(v) for g, v in sorted(m.items())}}


def diff_groups(a, b):
    ga, gb = a["groups"], b["groups"]
    rows = []
    for g in sorted(set(ga) | set(gb)):
        if g not in ga:
            rows.append({"change": "group-added", "group": g, "user": ""})
        if g not in gb:
            rows.append({"change": "group-removed", "group": g, "user": ""})
        for u in sorted(set(gb.get(g, [])) - set(ga.get(g, []))):
            rows.append({"change": "granted", "group": g, "user": u})
        for u in sorted(set(ga.get(g, [])) - set(gb.get(g, []))):
            rows.append({"change": "revoked", "group": g, "user": u})
    return rows


class PartialFailure(Exception):
    """A change failed after `applied` earlier changes were already made.

    `log_error` is set when the failure entry could not be written to the audit log."""

    def __init__(self, action, details, error, applied, log_error=None):
        self.action, self.details, self.error, self.applied = action, details, error, applied
        self.log_error = log_error
        super().__init__(f"{action} {details} failed after {applied} applied change(s): "
                         f"{auditlog.safe_error(error)}")


class Executor:
    """Plans changes; performs them only when apply=True on a writable directory.

    Each applied change writes an "intent" entry before the call and an "applied" entry after,
    so an interrupt can never leave an attempted change unlogged."""

    def __init__(self, directory, apply=False, log_path="crowdkeeper-audit.json"):
        if apply and not directory.writable:
            raise PermissionError("demo mode never writes; drop --apply or --demo")
        self.d, self.apply, self.log_path, self.plan = directory, apply, log_path, []
        self.applied = 0
        self.seq = 0
        self.log_error = None

    def _fail(self, action, details, e, seq):
        log_error = None
        try:
            auditlog.record(self.log_path, "failed", action, details, seq=seq,
                            error=auditlog.safe_error(e), applied_before_failure=self.applied)
        except Exception as le:  # the log itself is broken: never hide the original error
            log_error = self.log_error = le
            print(f"error: {action} failed: {auditlog.safe_error(e)}\n"
                  f"error: could not write the failure to audit log {self.log_path}: "
                  f"{auditlog.safe_error(le)}", file=sys.stderr)
        if not isinstance(e, Exception):
            raise e
        raise PartialFailure(action, details, e, self.applied, log_error) from e

    def do(self, action, fn, *args, **details):
        self.plan.append({"action": action, **details})
        if not self.apply:
            return
        self.seq += 1
        seq = self.seq
        try:
            auditlog.record(self.log_path, "intent", action, details, seq=seq)
        except Exception as e:  # can't log it, so don't do it
            self._fail(action, details, e, seq)
        try:
            fn(*args)
        except BaseException as e:  # incl. Ctrl-C
            self._fail(action, details, e, seq)
        self.applied += 1
        try:
            auditlog.record(self.log_path, "applied", action, details, seq=seq)
        except Exception as e:  # change happened and its intent entry is logged
            self._fail(action, details, e, seq)


def jml(directory, rows, ex):
    users = {u.name: u for u in directory.users()}
    for i, r in enumerate(rows, start=2):
        kind = (r.get("action") or "").strip().lower()
        name = (r.get("username") or "").strip()
        if not name:
            raise ValueError(f"CSV line {i}: missing username")
        groups = [g for g in (r.get("groups") or "").replace(";", " ").split() if g]
        cur = users.get(name)
        if kind == "joiner":
            if not cur:
                ex.do("create-user", ex.d.add_user, name, r.get("display_name", ""),
                      r.get("email", ""), user=name)
            for g in groups:
                if not cur or g not in cur.groups:
                    ex.do("add-to-group", ex.d.add_to_group, name, g, user=name, group=g)
        elif kind == "mover":
            if not cur:
                raise ValueError(f"mover {name}: no such user")
            for g in sorted(set(cur.groups) - set(groups)):
                ex.do("remove-from-group", ex.d.remove_from_group, name, g, user=name, group=g)
            for g in sorted(set(groups) - set(cur.groups)):
                ex.do("add-to-group", ex.d.add_to_group, name, g, user=name, group=g)
        elif kind == "leaver":
            if not cur:
                raise ValueError(f"leaver {name}: no such user")
            for g in cur.groups:
                ex.do("remove-from-group", ex.d.remove_from_group, name, g, user=name, group=g)
            if cur.active:
                ex.do("deactivate-user", ex.d.deactivate, name, user=name)
        else:
            raise ValueError(f"unknown action {kind!r} for {name}")
    return ex.plan


def fix(findings, ex):
    for f in findings:
        if f["fix"] == "deactivate":
            ex.do("deactivate-user", ex.d.deactivate, f["subject"], user=f["subject"],
                  reason=f["detail"])
        elif f["fix"] == "strip-groups":
            for g in f["groups"]:
                ex.do("remove-from-group", ex.d.remove_from_group, f["subject"], g,
                      user=f["subject"], group=g, reason="disabled user")
    return ex.plan


def report(directory, days=90, now=None):
    now = now or datetime.now(timezone.utc)
    users, groups = directory.users(), directory.groups()
    f = audit(directory, days, now)
    count = lambda t: sum(1 for x in f if x["type"] == t)
    lines = [f"# Crowd Access Review", "", f"Generated: {now:%Y-%m-%d %H:%M} UTC  ",
             f"Inactivity threshold: {days} days", "", "## Summary", "",
             "| Metric | Count |", "|---|---|",
             f"| Users | {len(users)} |", f"| Active users | {sum(u.active for u in users)} |",
             f"| Groups | {len(groups)} |",
             f"| Inactive users (>= {days}d) | {count('inactive')} |",
             f"| Active users with no groups | {count('no-groups')} |",
             f"| Disabled users still in groups | {count('disabled-in-groups')} |",
             f"| Empty groups | {count('empty-group')} |", "", "## Findings", ""]
    lines += [f"- **{x['type']}** `{md_safe(x['subject'])}`: {md_safe(x['detail'])} (recommended: {x['fix']})"
              for x in f] or ["No findings."]
    lines += ["", "## Group sizes", "", "| Group | Members |", "|---|---|"]
    lines += [f"| {md_safe(g)} | {len(m)} |" for g, m in export_groups(directory)["groups"].items()]
    lines += ["", "_Produced by crowdkeeper. Remediate with `crowdkeeper fix` (dry-run by default)._"]
    return "\n".join(lines) + "\n"
