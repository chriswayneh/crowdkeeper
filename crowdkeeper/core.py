import csv
import io
import json
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timezone

from . import auditlog
from .models import User


def check_days(days):
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError(f"days must be a positive whole number, got {days!r}")
    return days


def audit(directory, days=90, now=None):
    check_days(days)
    now = now or datetime.now(timezone.utc)
    users, groups = directory.users(), directory.groups()
    findings = []
    for u in users:
        if u.active and u.last_login is not None and (now - u.last_login).days >= days:
            findings.append(
                {
                    "type": "inactive",
                    "subject": u.name,
                    "detail": f"last login {(now - u.last_login).days}d ago",
                    "fix": "deactivate",
                }
            )
        elif u.active and u.last_login is None:
            # No lastAuthenticated: activity is UNKNOWN (new account, or Crowd never recorded
            # it, e.g. SSO/remembered sessions). Never auto-deactivate; flag for review only
            # once the account is older than the threshold (or its age is unknown).
            age = None if u.created is None else (now - u.created).days
            if age is None or age >= days:
                seen = "created date unknown" if age is None else f"account {age}d old"
                findings.append(
                    {
                        "type": "activity-unknown",
                        "subject": u.name,
                        "detail": f"no recorded login ({seen})",
                        "fix": "review",
                    }
                )
        if u.active and not u.groups:
            findings.append(
                {
                    "type": "no-groups",
                    "subject": u.name,
                    "detail": "active user in no groups",
                    "fix": "review",
                }
            )
        if not u.active and u.groups:
            findings.append(
                {
                    "type": "disabled-in-groups",
                    "subject": u.name,
                    "detail": "disabled but in: " + ", ".join(u.groups),
                    "fix": "strip-groups",
                    "groups": list(u.groups),
                }
            )
    used = {g for u in users for g in u.groups}
    for g in groups:
        if g not in used:
            findings.append(
                {"type": "empty-group", "subject": g, "detail": "group has no members", "fix": "review"}
            )
    return findings


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(v):
    """Neutralise spreadsheet formula injection (CWE-1236) in CSV cells."""
    v = "" if v is None else str(v)
    return "'" + v if v.startswith(_FORMULA) else v


_ESC = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}


def term_safe(v):
    """Make text safe to print: backslash, tab, CR, LF and every other control, format (bidi,
    zero-width) or line/paragraph separator character become Python-style escapes (\\\\, \\t,
    \\u001b, \\u202e, \\U000e0001), so output can't carry terminal escapes (ESC, OSC 8), reorder
    text or hide characters. A literal backslash is doubled, so a name that really contains the
    text "\\u001b" (shown as "\\\\u001b") never looks like a real ESC."""
    out = []
    for c in str(v):
        if c in _ESC:
            out.append(_ESC[c])
        elif unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp"):
            n = ord(c)
            out.append(f"\\u{n:04x}" if n <= 0xFFFF else f"\\U{n:08x}")
        else:
            out.append(c)
    return "".join(out)


def md_safe(v):
    """Escape Markdown table/link/emphasis/strikethrough characters, autolinks and HTML so names
    render as plain text under GFM (cmark-gfm autolink extension) and linkify. Every "." is
    escaped (no fuzzy domains), "://" is broken, and each run of "@" is put in a code span
    because cmark-gfm still links a backslash-escaped e-mail address."""
    s = term_safe(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\\", "\\\\").replace("`", "'")
    for ch in "|[]()!*_~.":
        s = s.replace(ch, "\\" + ch)
    s = s.replace("://", ":\\/\\/")
    return re.sub("@+", lambda m: "`" + m.group(0) + "`", s)


def md_code_safe(v):
    """Make text safe inside a Markdown code span, where escapes, HTML and autolinks are literal."""
    return term_safe(v).replace("`", "'")


def fmt(rows, cols, out="table"):
    if out == "json":
        return json.dumps(rows, indent=2, default=str)
    if out == "csv":
        b = io.StringIO()
        w = csv.DictWriter(b, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows({c: csv_safe(term_safe(r.get(c, ""))) for c in cols} for r in rows)
        return b.getvalue().rstrip("\n")
    if not rows:
        return "(nothing found)"
    cells = [[term_safe(r.get(c, "")) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    line = lambda vals: "  ".join(str(v).ljust(w) for v, w in zip(vals, widths, strict=False)).rstrip()
    return "\n".join([line(cols), line("-" * w for w in widths)] + [line(row) for row in cells])


class Snapshot:
    """One read of a directory: users() and groups() are fetched once and reused, so every
    section of a report describes the same state (and the directory is not read repeatedly)."""

    writable = False

    def __init__(self, directory):
        self._users, self._groups = directory.users(), list(directory.groups())

    def users(self):
        return [
            User(u.name, u.display_name, u.email, u.active, u.last_login, list(u.groups), u.created)
            for u in self._users
        ]

    def groups(self):
        return list(self._groups)


def export_groups(directory):
    m = {g: [] for g in directory.groups()}
    for u in directory.users():
        for g in u.groups:
            m.setdefault(g, []).append(u.name)
    return {"groups": {g: sorted(v) for g, v in sorted(m.items())}}


def _snapshot_groups(snap, which):
    if not isinstance(snap, dict) or not isinstance(snap.get("groups"), dict):
        raise ValueError(
            f"{which} snapshot: expected an object with a 'groups' mapping "
            "(made by `crowdkeeper groups export`)"
        )
    for g, members in snap["groups"].items():
        if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
            raise ValueError(f"{which} snapshot: group {g!r} must map to a list of usernames")
    return snap["groups"]


def diff_groups(a, b):
    ga, gb = _snapshot_groups(a, "first"), _snapshot_groups(b, "second")
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
        super().__init__(
            f"{action} {details} failed after {applied} applied change(s): {auditlog.safe_error(error)}"
        )


def _rejected(e):
    """True when the directory definitely refused the change (it was never made)."""
    status = getattr(e, "status", None)
    return isinstance(status, int) and 400 <= status < 500


class Executor:
    """Plans changes; performs them only when apply=True on a writable directory.

    Each applied change writes an "intent" entry before the call and an "applied" entry after,
    so an interrupt can never leave an attempted change unlogged."""

    def __init__(self, directory, apply=False, log_path="crowdkeeper-audit.json"):
        if apply and not directory.writable:
            raise PermissionError("demo mode never writes; drop --apply or --demo")
        self.d, self.apply, self.log_path, self.plan = directory, apply, log_path, []
        self.applied = 0
        self.ops = []  # (action, fn, args, details): the exact plan, replayable by execute()
        self.seq = 0
        self.log_error = None
        self.run_id = uuid.uuid4().hex  # seq restarts each run; (run_id, seq) is unique

    def _fail(self, action, details, e, seq, stage):
        # stage: intent_log (change not attempted), change (call failed),
        # applied_log (the change WAS made; only its "applied" line failed to write).
        # change_applied: True for applied_log; False only when the change provably did not
        # happen (intent_log, or Crowd answered with a 4xx rejection); otherwise None (unknown):
        # an interrupt, timeout, lost response or 5xx may come after Crowd committed the change.
        # applied_before_failure counts every change made so far, incl. this one if change_applied.
        log_error = None
        if stage == "applied_log":
            applied = True
        elif stage == "intent_log" or _rejected(e):
            applied = False
        else:
            applied = None
        try:
            auditlog.record(
                self.log_path,
                "failed",
                action,
                details,
                seq=seq,
                run_id=self.run_id,
                stage=stage,
                change_applied=applied,
                error=auditlog.safe_error(e),
                applied_before_failure=self.applied,
            )
        except Exception as le:  # the log itself is broken: never hide the original error
            log_error = self.log_error = le
            print(
                f"error: {action} failed: {term_safe(auditlog.safe_error(e))}\n"
                f"error: could not write the failure to audit log {term_safe(self.log_path)}: "
                f"{term_safe(auditlog.safe_error(le))}",
                file=sys.stderr,
            )
        if not isinstance(e, Exception):
            raise e
        raise PartialFailure(action, details, e, self.applied, log_error) from e

    def execute(self, ops):
        """Apply an already-approved plan exactly as previewed (no re-planning)."""
        for action, fn, args, details in ops:
            self.do(action, fn, *args, **details)
        return self.plan

    def do(self, action, fn, *args, **details):
        self.plan.append({"action": action, **details})
        self.ops.append((action, fn, args, details))
        if not self.apply:
            return
        self.seq += 1
        seq = self.seq
        try:
            auditlog.record(self.log_path, "intent", action, details, seq=seq, run_id=self.run_id)
        except Exception as e:  # can't log it, so don't do it
            self._fail(action, details, e, seq, "intent_log")
        try:
            fn(*args)
        except BaseException as e:  # incl. Ctrl-C
            self._fail(action, details, e, seq, "change")
        self.applied += 1
        try:
            auditlog.record(self.log_path, "applied", action, details, seq=seq, run_id=self.run_id)
        except BaseException as e:  # incl. Ctrl-C: the change happened; log it, then re-raise
            self._fail(action, details, e, seq, "applied_log")


JML_REQUIRED = ("action", "username")
JML_COLUMNS = (*JML_REQUIRED, "display_name", "email", "groups")


NO_GROUPS = {"-", "none"}


def _tokens(v):
    """Split a groups cell into (name, quoted) pairs. A token wrapped in single quotes, e.g.
    'none' or '-', is a literal group name and never the remove-all marker."""
    out = []
    for g in (v or "").replace(";", " ").split():
        if len(g) >= 3 and g[0] == g[-1] == "'":
            out.append((g[1:-1], True))
        else:
            out.append((g, False))
    return out


def _is_marker(tok):
    name, quoted = tok
    return not quoted and name.lower() in NO_GROUPS


def _groups_of(r):
    """None = don't touch groups: column missing or a blank cell (empty,
    spaces, or only ';'). [] = the bare marker '-' or 'none': remove every membership.
    Otherwise the listed groups. A blank cell is never read as "remove all"."""
    v = r.get("groups")
    if v is None:
        return None
    toks = _tokens(v)
    if not toks:
        return None
    if any(_is_marker(t) for t in toks):
        return []
    return [name for name, _ in toks]


def _groups_error(r):
    v = r.get("groups") or ""
    toks = _tokens(v)
    if len(toks) > 1 and any(_is_marker(t) for t in toks):
        return f"'-'/'none' (remove all groups) cannot be combined with groups: {v.strip()!r}"
    return None


JML_ACTIONS = ("joiner", "mover", "leaver")


class JmlInputError(ValueError):
    """The JML CSV content is invalid; nothing was planned or changed (CLI exit 2)."""


def validate_jml(rows, fieldnames, known_groups, known_users=None, lines=None):
    """Check the whole CSV before any change is planned or made; raise ValueError listing every
    bad line. Checks: required columns, extra values, action, empty username, groups, and (when
    known_users is given) that each mover/leaver exists, counting users created by earlier
    joiner rows. lines gives each row's real file line (default: row index + 2)."""
    missing = [c for c in JML_REQUIRED if c not in (fieldnames or [])]
    if missing:
        raise JmlInputError(f"CSV header is missing required column(s): {', '.join(missing)}")
    known, errors = set(known_groups), []
    users = None if known_users is None else set(known_users)
    for i, r in zip(_line_nos(rows, lines), rows, strict=True):
        kind = (r.get("action") or "").strip().lower()
        name = (r.get("username") or "").strip()
        if kind not in JML_ACTIONS:
            errors.append(f"line {i}: unknown action {kind!r} (expected joiner, mover or leaver)")
        if not name:
            errors.append(f"line {i}: missing username")
        elif users is not None:
            if kind == "joiner":
                users.add(name)
            elif kind in ("mover", "leaver") and name not in users:
                errors.append(f"line {i}: {kind} {name}: no such user")
        if None in r:
            errors.append(f"line {i}: more values than header columns")
        if _groups_error(r):
            errors.append(f"line {i}: {_groups_error(r)}")
        for g in _groups_of(r) or []:
            if g not in known:
                errors.append(f"line {i}: unknown group {g!r}")
    if errors:
        raise JmlInputError("invalid JML CSV, nothing changed:\n  " + "\n  ".join(errors))


def _line_nos(rows, lines):
    if lines is None:
        return range(2, len(rows) + 2)
    if len(lines) != len(rows):
        raise ValueError("lines must have one entry per row")
    return lines


def jml(directory, rows, ex, fieldnames=None, lines=None):
    """Rows are applied in order against a projected state, so several rows for one user
    (e.g. mover then mover back, or joiner twice) see the effect of the earlier rows."""
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else list(JML_REQUIRED)
    users = {u.name: u for u in directory.users()}
    validate_jml(rows, fieldnames, directory.groups(), users, lines)  # before ANY ex.do()
    for i, r in zip(_line_nos(rows, lines), rows, strict=True):
        kind = (r.get("action") or "").strip().lower()
        name = (r.get("username") or "").strip()
        if not name:
            raise ValueError(f"CSV line {i}: missing username")
        groups = _groups_of(r)
        cur = users.get(name)
        if kind == "joiner":
            if not cur:
                ex.do(
                    "create-user",
                    ex.d.add_user,
                    name,
                    r.get("display_name") or "",
                    r.get("email") or "",
                    user=name,
                )
                cur = users[name] = User(name, r.get("display_name") or "", r.get("email") or "")
            for g in groups or []:
                if g not in cur.groups:
                    ex.do("add-to-group", ex.d.add_to_group, name, g, user=name, group=g)
                    cur.groups = sorted([*cur.groups, g])
        elif kind == "mover":
            if not cur:
                raise ValueError(f"CSV line {i}: mover {name}: no such user")
            if groups is None:  # missing/blank groups: leave memberships alone
                continue
            for g in sorted(set(cur.groups) - set(groups)):
                ex.do("remove-from-group", ex.d.remove_from_group, name, g, user=name, group=g)
            for g in sorted(set(groups) - set(cur.groups)):
                ex.do("add-to-group", ex.d.add_to_group, name, g, user=name, group=g)
            cur.groups = sorted(set(groups))
        elif kind == "leaver":
            if not cur:
                raise ValueError(f"CSV line {i}: leaver {name}: no such user")
            # deactivate first: if a later group removal fails, the account is already locked
            if cur.active:
                ex.do("deactivate-user", ex.d.deactivate, name, user=name)
                cur.active = False
            for g in cur.groups:
                ex.do("remove-from-group", ex.d.remove_from_group, name, g, user=name, group=g)
            cur.groups = []
        else:
            raise ValueError(f"CSV line {i}: unknown action {kind!r} for {name}")
    return ex.plan


def fix(findings, ex):
    for f in findings:
        if f["fix"] == "deactivate":
            ex.do("deactivate-user", ex.d.deactivate, f["subject"], user=f["subject"], reason=f["detail"])
        elif f["fix"] == "strip-groups":
            for g in f["groups"]:
                ex.do(
                    "remove-from-group",
                    ex.d.remove_from_group,
                    f["subject"],
                    g,
                    user=f["subject"],
                    group=g,
                    reason="disabled user",
                )
    return ex.plan


def report(directory, days=90, now=None):
    now = now or datetime.now(timezone.utc)
    check_days(days)
    directory = Snapshot(directory)
    users, groups = directory.users(), directory.groups()
    f = audit(directory, days, now)
    count = lambda t: sum(1 for x in f if x["type"] == t)
    lines = [
        "# Crowd Access Review",
        "",
        f"Generated: {now:%Y-%m-%d %H:%M} UTC  ",
        f"Inactivity threshold: {days} days",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Users | {len(users)} |",
        f"| Active users | {sum(u.active for u in users)} |",
        f"| Groups | {len(groups)} |",
        f"| Inactive users (>= {days}d) | {count('inactive')} |",
        f"| Active users with unknown login activity | {count('activity-unknown')} |",
        f"| Active users with no groups | {count('no-groups')} |",
        f"| Disabled users still in groups | {count('disabled-in-groups')} |",
        f"| Empty groups | {count('empty-group')} |",
        "",
        "## Findings",
        "",
    ]
    lines += [
        f"- **{x['type']}** `{md_code_safe(x['subject'])}`: {md_safe(x['detail'])} (recommended: {x['fix']})"
        for x in f
    ] or ["No findings."]
    lines += ["", "## Group sizes", "", "| Group | Members |", "|---|---|"]
    lines += [f"| {md_safe(g)} | {len(m)} |" for g, m in export_groups(directory)["groups"].items()]
    lines += ["", "_Produced by crowdkeeper. Remediate with `crowdkeeper fix` (dry-run by default)._"]
    return "\n".join(lines) + "\n"
