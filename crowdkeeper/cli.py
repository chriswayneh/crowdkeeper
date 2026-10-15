import argparse
import csv
import json
import logging
import os
import sys

from . import __version__, core
from .client import CrowdClient, CrowdError
from .demo import NOW, DemoDirectory

FCOLS = ["type", "subject", "detail", "fix"]


def _dir(args):
    if args.demo or os.environ.get("CROWDKEEPER_DEMO") == "1":
        return DemoDirectory(), NOW
    return CrowdClient.from_env(), None


def _confirm(args, n):
    if args.yes:
        return True
    return input(f"Apply {n} change(s) to Crowd? Type 'yes' to continue: ").strip() == "yes"


def _run_plan(args, d, planner):
    if args.apply and not d.writable:
        print("demo mode never writes; showing the dry-run plan instead.", file=sys.stderr)
        args.apply = False
    plan = planner(core.Executor(d, apply=False))
    print(core.fmt(plan, ["action", "user", "group"], args.output))
    if not args.apply:
        print(f"\nDry run: {len(plan)} change(s) planned, nothing written. Use --apply to execute.")
        return 0
    if not plan or not _confirm(args, len(plan)):
        print("Aborted, nothing changed." if plan else "Nothing to do.")
        return 0
    ex = core.Executor(d, apply=True, log_path=args.log)
    planner(ex)
    print(f"\nApplied {len(ex.plan)} change(s). Audit log: {args.log}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="crowdkeeper", description=__doc__ or
                                "Access hygiene and JML toolkit for Atlassian Crowd")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--demo", action="store_true", help="use the built-in fake directory")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def out(sp):
        sp.add_argument("-o", "--output", choices=["table", "json", "csv"], default="table")

    a = sub.add_parser("audit", help="report hygiene problems")
    a.add_argument("--days", type=int, default=90)
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
            sp.add_argument("--days", type=int, default=90)
        sp.add_argument("--apply", action="store_true", help="actually make changes")
        sp.add_argument("-y", "--yes", action="store_true", help="skip confirm prompt")
        sp.add_argument("--log", default="crowdkeeper-audit.json", help="JSON audit log path")
        out(sp)
    r = sub.add_parser("report", help="one-page Markdown summary")
    r.add_argument("--days", type=int, default=90)
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
                print(f"Wrote {args.file}")
            else:
                print(text)
        elif args.cmd == "report":
            md = core.report(d, args.days, now)
            if args.file:
                with open(args.file, "w") as f:
                    f.write(md)
                print(f"Wrote {args.file}")
            else:
                print(md, end="")
        elif args.cmd == "jml":
            with open(args.csv, newline="") as f:
                rows = list(csv.DictReader(f))
            return _run_plan(args, d, lambda ex: core.jml(d, rows, ex))
        elif args.cmd == "fix":
            findings = core.audit(d, args.days, now)
            return _run_plan(args, d, lambda ex: core.fix(findings, ex))
    except (CrowdError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
