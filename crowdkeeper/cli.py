import argparse
import csv
import json
import logging
import os
import sys

import requests

from . import __version__, auditlog, core
from .client import CrowdClient, CrowdError
from .demo import NOW, DemoDirectory

FCOLS = ["type", "subject", "detail", "fix"]


def _dir(args):
    if args.demo or os.environ.get("CROWDKEEPER_DEMO") == "1":
        return DemoDirectory(), NOW
    return CrowdClient.from_env(insecure=getattr(args, "insecure", False)), None


class _CsvError(Exception):
    """Malformed JML CSV (bad header or broken quoting); nothing is planned or changed."""


def _read_jml_csv(path):
    """Read a JML CSV strictly: unique, non-blank headers and well-formed quoting."""
    with open(path, newline="") as f:
        reader = csv.reader(f, strict=True)
        try:
            header = next(reader, None)
            if header is None:
                return [], None
            seen, cols = set(), []
            for h in header:
                name = h.strip()
                if not name:
                    raise _CsvError(f"{path}: line 1: blank column header")
                if name in seen:
                    raise _CsvError(f"{path}: line 1: duplicate column header {name!r}")
                seen.add(name)
                cols.append(h)
            rows = []
            while True:
                start = reader.line_num + 1
                try:
                    vals = next(reader)
                except StopIteration:
                    break
                except csv.Error as e:
                    raise _CsvError(f"{path}: line {start}: malformed CSV ({e})") from None
                if not vals:
                    continue
                row = dict(zip(cols, vals, strict=False))
                for c in cols[len(vals) :]:
                    row[c] = None
                if len(vals) > len(cols):
                    row[None] = vals[len(cols) :]
                rows.append(row)
        except csv.Error as e:
            raise _CsvError(f"{path}: line 1: malformed CSV header ({e})") from None
    return rows, cols


REFUSED = None  # _confirm result: non-TTY stdin without -y (caller exits 2)


def _confirm(args, n):
    """True to apply, False if declined at the prompt, REFUSED (None) if stdin isn't a TTY."""
    if args.yes:
        return True
    if not sys.stdin.isatty():  # piped/redirected stdin can't be a typed "yes": refuse
        print("stdin is not a terminal; pass -y to apply non-interactively.", file=sys.stderr)
        return REFUSED
    try:
        sys.stderr.write(f"Apply {n} change(s) to Crowd? Type 'yes' to continue: ")
        sys.stderr.flush()
        return input().strip() == "yes"
    except EOFError:  # non-interactive without --yes: treat as "no"
        return False


def _run_plan(args, d, planner):
    if args.apply and not d.writable:
        print("demo mode never writes; showing the dry-run plan instead.", file=sys.stderr)
        args.apply = False
    preview = core.Executor(d, apply=False)
    plan = planner(preview)
    # stdout carries only the selected format; prompts and status go to stderr
    print(core.fmt(plan, ["action", "user", "group"], args.output))
    if not args.apply:
        print(
            f"Dry run: {len(plan)} change(s) planned, nothing written. Use --apply to execute.",
            file=sys.stderr,
        )
        return 0
    if not plan:
        print("Nothing to do.", file=sys.stderr)
        return 0
    ok = _confirm(args, len(plan))
    if not ok:
        print("Aborted, nothing changed.", file=sys.stderr)
        return 2 if ok is REFUSED else 0
    ex = core.Executor(d, apply=True, log_path=args.log)
    try:
        ex.execute(preview.ops)  # exactly the confirmed plan, never re-planned
    except core.PartialFailure as e:
        where = (
            f"the audit log {args.log} could not be written, so check it by hand"
            if e.log_error
            else f"all of them and the failure are recorded in {args.log}"
        )
        print(
            f"\nerror: {e}\nStopped. {e.applied} change(s) were applied before the failure; {where}",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        where = (
            f"the audit log {args.log} could not be written, so check it by hand"
            if ex.log_error
            else f"all of them and the interrupted change are recorded in {args.log}"
        )
        print(
            f"\nInterrupted. {ex.applied} change(s) were applied before the interrupt; {where}",
            file=sys.stderr,
        )
        return 1
    print(f"Applied {len(ex.plan)} change(s). Audit log: {args.log}", file=sys.stderr)
    return 0


def _days(v):
    try:
        return core.check_days(int(v))
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a positive whole number, got {v!r}") from None


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="crowdkeeper", description=__doc__ or "Access hygiene and JML toolkit for Atlassian Crowd"
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--demo", action="store_true", help="use the built-in fake directory")
    p.add_argument(
        "--insecure",
        action="store_true",
        help="allow a plain http:// CROWD_URL (sends the app password unencrypted)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def out(sp):
        sp.add_argument("-o", "--output", choices=["table", "json", "csv"], default="table")

    a = sub.add_parser("audit", help="report hygiene problems")
    a.add_argument("--days", type=_days, default=90)
    out(a)
    g = sub.add_parser("groups", help="export or diff group membership")
    gs = g.add_subparsers(dest="gcmd", required=True)
    ge = gs.add_parser("export")
    ge.add_argument("-f", "--file", help="write to file instead of stdout")
    gd = gs.add_parser("diff")
    gd.add_argument("a")
    gd.add_argument("b")
    out(gd)
    for name, h in (("jml", "joiner/mover/leaver from CSV"), ("fix", "apply audit cleanups")):
        sp = sub.add_parser(name, help=h)
        if name == "jml":
            sp.add_argument("csv")
        else:
            sp.add_argument("--days", type=_days, default=90)
        sp.add_argument("--apply", action="store_true", help="actually make changes")
        sp.add_argument("-y", "--yes", action="store_true", help="skip confirm prompt")
        sp.add_argument("--log", default="crowdkeeper-audit.json", help="JSON audit log path")
        out(sp)
    r = sub.add_parser("report", help="one-page Markdown summary")
    r.add_argument("--days", type=_days, default=90)
    r.add_argument("-f", "--file")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    try:
        if args.cmd == "groups" and args.gcmd == "diff":
            with open(args.a) as fa, open(args.b) as fb:
                rows = core.diff_groups(json.load(fa), json.load(fb))
            print(core.fmt(rows, ["change", "group", "user"], args.output))
            return 0
        d, now = _dir(args)
        if args.cmd == "audit":
            print(core.fmt(core.audit(d, args.days, now), FCOLS, args.output))
        elif args.cmd == "groups":
            text = json.dumps(core.export_groups(d), indent=2)
            if args.file:
                with open(args.file, "w") as f:
                    f.write(text + "\n")
                print(f"Wrote {args.file}", file=sys.stderr)
            else:
                print(text)
        elif args.cmd == "report":
            md = core.report(d, args.days, now)
            if args.file:
                with open(args.file, "w") as f:
                    f.write(md)
                print(f"Wrote {args.file}", file=sys.stderr)
            else:
                print(md, end="")
        elif args.cmd == "jml":
            try:
                rows, cols = _read_jml_csv(args.csv)
            except _CsvError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            return _run_plan(args, d, lambda ex: core.jml(d, rows, ex, cols))
        elif args.cmd == "fix":
            findings = core.audit(d, args.days, now)
            return _run_plan(args, d, lambda ex: core.fix(findings, ex))
    except (CrowdError, ValueError, OSError, requests.RequestException) as e:
        print(f"error: {auditlog.scrub(e)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
