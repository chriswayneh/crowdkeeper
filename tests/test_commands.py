import json

import pytest

from crowdkeeper import auditlog, core
from crowdkeeper.cli import main
from crowdkeeper.demo import NOW, DemoDirectory


@pytest.fixture
def d():
    return DemoDirectory()


def test_demo_size(d):
    assert len(d.users()) == 25 and len(d.groups()) == 8


def test_audit_finds_planted_problems(d):
    f = core.audit(d, 90, NOW)
    by = lambda t: {x["subject"] for x in f if x["type"] == t}
    assert by("inactive") == {"frank", "heidi", "olivia", "rupert", "svc-backup"}
    assert by("no-groups") == {"olivia", "victor", "svc-backup"}
    assert by("disabled-in-groups") == {"ivan", "mallory", "trent"}
    assert by("empty-group") == {"legacy-sox-approvers"}


@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_audit_cli_formats(fmt, capsys):
    assert main(["--demo", "audit", "-o", fmt]) == 0
    out = capsys.readouterr().out
    assert "legacy-sox-approvers" in out
    if fmt == "json":
        assert isinstance(json.loads(out), list)
    if fmt == "csv":
        assert out.startswith("type,subject,detail,fix")


def test_env_demo(monkeypatch, capsys):
    monkeypatch.setenv("CROWDKEEPER_DEMO", "1")
    assert main(["audit"]) == 0
    assert "mallory" in capsys.readouterr().out


def test_groups_export_and_diff(tmp_path, capsys):
    a = tmp_path / "a.json"
    assert main(["--demo", "groups", "export", "-f", str(a)]) == 0
    data = json.loads(a.read_text())
    assert "alice" in data["groups"]["jira-admins"]
    data["groups"]["jira-admins"].append("zoe")
    data["groups"]["finance"].remove("carol")
    b = tmp_path / "b.json"
    b.write_text(json.dumps(data))
    capsys.readouterr()
    assert main(["groups", "diff", str(a), str(b), "-o", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {"change": "granted", "group": "jira-admins", "user": "zoe"} in rows
    assert {"change": "revoked", "group": "finance", "user": "carol"} in rows


def test_jml_plan(d, tmp_path):
    rows = [{"action": "joiner", "username": "newhire", "groups": "jira-users;hr"},
            {"action": "mover", "username": "bob", "groups": "jira-users confluence-users"},
            {"action": "leaver", "username": "frank", "groups": ""}]
    plan = core.jml(d, rows, core.Executor(d))
    acts = [(p["action"], p.get("user"), p.get("group")) for p in plan]
    assert ("create-user", "newhire", None) in acts
    assert ("remove-from-group", "bob", "bitbucket-users") in acts
    assert ("add-to-group", "bob", "confluence-users") in acts
    assert ("deactivate-user", "frank", None) in acts


def test_jml_cli_dry_run_default(tmp_path, capsys):
    c = tmp_path / "j.csv"
    c.write_text("action,username,groups\nleaver,alice,\n")
    log = tmp_path / "log.json"
    assert main(["--demo", "jml", str(c), "--apply", "-y", "--log", str(log)]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert not log.exists()


def test_fix_dry_run_and_demo_never_writes(d, capsys, tmp_path):
    with pytest.raises(PermissionError):
        core.Executor(d, apply=True)
    log = tmp_path / "l.json"
    assert main(["--demo", "fix", "--log", str(log)]) == 0
    out = capsys.readouterr().out
    assert "deactivate-user" in out and "Dry run: 10 change(s)" in out
    assert not log.exists()


class FakeWritable(DemoDirectory):
    writable = True

    def __init__(self):
        super().__init__()
        self.calls = []

    def deactivate(self, u):
        self.calls.append(("deactivate", u))

    def remove_from_group(self, u, g):
        self.calls.append(("remove", u, g))


def test_fix_apply_writes_audit_log(tmp_path):
    d = FakeWritable()
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    core.fix(core.audit(d, 90, NOW), ex)
    entries = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(d.calls) == 10 and len(entries) == 20
    assert all("ts" in e for e in entries)
    # every change: intent entry, then applied entry, same seq and detail
    for i in range(0, 20, 2):
        a, b = entries[i], entries[i + 1]
        assert (a["event"], b["event"]) == ("intent", "applied")
        assert a["seq"] == b["seq"] == i // 2 + 1
        assert a["action"] == b["action"] and a["detail"] == b["detail"] and a["detail"]


def test_auditlog_drops_passwords(tmp_path):
    p = tmp_path / "x.json"
    auditlog.record(str(p), "applied", "create-user", {"user": "u", "password": "hunter2"})
    assert "hunter2" not in p.read_text()


def test_report(tmp_path):
    f = tmp_path / "r.md"
    assert main(["--demo", "report", "-f", str(f)]) == 0
    md = f.read_text()
    assert md.startswith("# Crowd Access Review")
    assert "| Disabled users still in groups | 3 |" in md


def test_missing_env_errors(monkeypatch, capsys):
    for k in ("CROWD_URL", "CROWD_APP", "CROWD_APP_PASSWORD", "CROWDKEEPER_DEMO"):
        monkeypatch.delenv(k, raising=False)
    assert main(["audit"]) == 1


def test_csv_output_neutralises_formulas():
    out = core.fmt([{"type": "=HYPERLINK(\"x\")", "subject": "+cmd", "detail": "-1", "fix": "@a"}],
                   ["type", "subject", "detail", "fix"], "csv")
    row = out.splitlines()[1]
    assert row.startswith("\"'=HYPERLINK") and ",'+cmd,'-1,'@a" in row


def test_jml_rejects_malformed_rows(d, tmp_path):
    with pytest.raises(ValueError, match="missing username"):
        core.jml(d, [{"action": "joiner"}], core.Executor(d))
    p = tmp_path / "bad.csv"
    p.write_text("foo,bar\n1,2\n")
    assert main(["--demo", "jml", str(p)]) == 1


def test_confirm_eof_aborts(monkeypatch):
    from crowdkeeper import cli

    def eof(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert cli._confirm(type("A", (), {"yes": False})(), 3) is False


def test_report_escapes_markdown():
    assert core.md_safe("a|b`c") == "a\\|b'c"


def test_http_url_warns(caplog):
    from crowdkeeper.client import CrowdClient
    CrowdClient("http://crowd.local", "app", "pw")
    assert "not https" in caplog.text and "pw" not in caplog.text


class FailingWritable(FakeWritable):
    """Fails on the Nth write call, after earlier calls succeeded."""

    def __init__(self, fail_at):
        super().__init__()
        self.fail_at = fail_at

    def _maybe_fail(self):
        if len(self.calls) == self.fail_at:
            raise RuntimeError("boom secret-pw-123 at https://app:secret-pw-123@crowd.example")

    def deactivate(self, u):
        self._maybe_fail()
        super().deactivate(u)

    def remove_from_group(self, u, g):
        self._maybe_fail()
        super().remove_from_group(u, g)

    def add_to_group(self, u, g):
        self._maybe_fail()
        self.calls.append(("add", u, g))

    def add_user(self, *a):
        self._maybe_fail()
        self.calls.append(("create", a[0]))



def _entries(log):
    return [json.loads(l) for l in log.read_text().splitlines()]


def _check_partial(log, applied, capsys):
    entries = _entries(log)
    # applied changes: intent+applied pairs; then the failed change's intent and failure
    assert len(entries) == 2 * applied + 2
    assert [e["event"] for e in entries[:-2]] == ["intent", "applied"] * applied
    intent, fail = entries[-2], entries[-1]
    assert intent["event"] == "intent" and fail["event"] == "failed"
    assert fail["action"] == intent["action"] and fail["seq"] == intent["seq"] == applied + 1
    assert fail["applied_before_failure"] == applied
    assert "RuntimeError" in fail["error"] and "ts" in fail
    assert "secret-pw-123" not in log.read_text()
    assert "secret-pw-123" not in capsys.readouterr().err


def test_fix_partial_failure_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROWD_APP_PASSWORD", "secret-pw-123")
    d = FailingWritable(fail_at=3)
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(core.PartialFailure) as ei:
        core.fix(core.audit(d, 90, NOW), ex)
    assert ei.value.applied == 3 == len(d.calls)
    _check_partial(log, 3, capsys)


def test_jml_partial_failure_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CROWD_APP_PASSWORD", "secret-pw-123")
    d = FailingWritable(fail_at=2)
    name = next(u for u in d.users() if len(u.groups) >= 2).name
    rows = [{"action": "joiner", "username": "newbie", "groups": "g-a g-b g-c"},
            {"action": "leaver", "username": name, "groups": ""}]
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(core.PartialFailure):
        core.jml(d, rows, ex)
    _check_partial(log, 2, capsys)


@pytest.mark.parametrize("cmd", ["fix", "jml"])
def test_cli_partial_failure_exits_nonzero(cmd, tmp_path, monkeypatch, capsys):
    from crowdkeeper import cli
    monkeypatch.setenv("CROWD_APP_PASSWORD", "secret-pw-123")
    d = FailingWritable(fail_at=1)
    log = tmp_path / "audit.json"
    args = type("A", (), {"apply": True, "output": "table", "log": str(log), "yes": True})()
    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    if cmd == "fix":
        planner = lambda ex: core.fix(core.audit(d, 90, NOW), ex)
    else:
        rows = [{"action": "joiner", "username": "newbie", "groups": "g-a g-b"}]
        planner = lambda ex: core.jml(d, rows, ex)
    assert cli._run_plan(args, d, planner) == 1
    err = capsys.readouterr().err
    assert "1 change(s) were applied" in err and "secret-pw-123" not in err
    entries = _entries(log)
    assert [e["event"] for e in entries] == ["intent", "applied", "intent", "failed"]


def test_interrupt_mid_apply_still_logged(tmp_path):
    class Interrupting(FakeWritable):
        def deactivate(self, u):
            raise KeyboardInterrupt
    d = Interrupting()
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(KeyboardInterrupt):
        core.fix(core.audit(d, 90, NOW), ex)
    assert [e["event"] for e in _entries(log)][-2:] == ["intent", "failed"]


def test_cli_interrupt_exits_1_without_traceback(tmp_path, monkeypatch, capsys):
    from crowdkeeper import cli

    class Interrupting(FakeWritable):
        def deactivate(self, u):
            raise KeyboardInterrupt
    d = Interrupting()
    log = tmp_path / "audit.json"
    args = type("A", (), {"apply": True, "output": "table", "log": str(log), "yes": True})()
    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    assert cli._run_plan(args, d, lambda ex: core.fix(core.audit(d, 90, NOW), ex)) == 1
    assert "Interrupted" in capsys.readouterr().err
    assert [e["event"] for e in _entries(log)][-2:] == ["intent", "failed"]


def test_intent_logged_before_change_runs(tmp_path):
    """The intent entry is on disk before the directory call happens (Ctrl-C safety)."""
    log = tmp_path / "audit.json"
    seen = []

    class Peeking(FakeWritable):
        def deactivate(self, u):
            seen.append(_entries(log)[-1])
            super().deactivate(u)
    d = Peeking()
    core.fix(core.audit(d, 90, NOW), core.Executor(d, apply=True, log_path=str(log)))
    assert seen and all(e["event"] == "intent" and e["detail"].get("user") for e in seen)


def test_hard_kill_mid_change_leaves_intent(tmp_path):
    """Simulate the process dying inside a change (no except handler runs): intent is logged."""
    class Dying(FakeWritable):
        def deactivate(self, u):
            raise SystemExit  # BaseException; stands in for a kill
    d = Dying()
    log = tmp_path / "audit.json"
    with pytest.raises(SystemExit):
        core.fix(core.audit(d, 90, NOW), core.Executor(d, apply=True, log_path=str(log)))
    events = [e["event"] for e in _entries(log)]
    assert "intent" in events and events.count("intent") == events.count("applied") + 1


def test_failure_log_unwritable_still_reports_original_error(tmp_path, monkeypatch, capsys):
    from crowdkeeper import cli
    monkeypatch.setenv("CROWD_APP_PASSWORD", "secret-pw-123")
    d = FailingWritable(fail_at=1)
    log = tmp_path / "audit.json"
    real = auditlog.record

    def flaky(path, event, *a, **k):
        if event == "failed":
            raise OSError("No space left on device")
        return real(path, event, *a, **k)
    monkeypatch.setattr(auditlog, "record", flaky)
    args = type("A", (), {"apply": True, "output": "table", "log": str(log), "yes": True})()
    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    assert cli._run_plan(args, d, lambda ex: core.fix(core.audit(d, 90, NOW), ex)) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err  # the original error
    assert "No space left on device" in err and "could not be written" in err
    assert "secret-pw-123" not in err


def test_interrupt_with_unwritable_log_still_exits_1(tmp_path, monkeypatch, capsys):
    from crowdkeeper import cli

    class Interrupting(FakeWritable):
        def deactivate(self, u):
            raise KeyboardInterrupt
    real = auditlog.record

    def flaky(path, event, *a, **k):
        if event == "failed":
            raise OSError("read-only file system")
        return real(path, event, *a, **k)
    monkeypatch.setattr(auditlog, "record", flaky)
    d = Interrupting()
    args = type("A", (), {"apply": True, "output": "table",
                          "log": str(tmp_path / "a.json"), "yes": True})()
    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    assert cli._run_plan(args, d, lambda ex: core.fix(core.audit(d, 90, NOW), ex)) == 1
    err = capsys.readouterr().err
    assert "KeyboardInterrupt" in err and "read-only file system" in err


def test_intent_write_failure_skips_change(tmp_path, monkeypatch):
    d = FakeWritable()
    monkeypatch.setattr(auditlog, "record",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    ex = core.Executor(d, apply=True, log_path=str(tmp_path / "a.json"))
    with pytest.raises(core.PartialFailure) as ei:
        core.fix(core.audit(d, 90, NOW), ex)
    assert d.calls == [] and ei.value.log_error is not None


def test_detail_keys_cannot_overwrite_log_fields(tmp_path):
    log = tmp_path / "a.json"
    auditlog.record(str(log), "failed", "deactivate-user",
                    {"event": "applied", "action": "x", "error": "fake", "ts": "1970", "user": "bob"},
                    seq=3, error="real")
    e = _entries(log)[0]
    assert e["event"] == "failed" and e["action"] == "deactivate-user" and e["error"] == "real"
    assert e["ts"] != "1970" and e["seq"] == 3
    assert e["detail"] == {"event": "applied", "action": "x", "error": "fake",
                           "ts": "1970", "user": "bob"}


def test_executor_detail_collision_kept_nested(tmp_path):
    d = FailingWritable(fail_at=0)
    log = tmp_path / "a.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(core.PartialFailure):
        ex.do("deactivate-user", d.deactivate, "bob", user="bob", error="spoof",
              applied_before_failure=99)
    fail = _entries(log)[-1]
    assert fail["applied_before_failure"] == 0 and "RuntimeError" in fail["error"]
    assert fail["detail"] == {"user": "bob", "error": "spoof", "applied_before_failure": 99}


def test_run_id_distinguishes_runs_in_same_log(tmp_path):
    log = tmp_path / "a.json"
    for _ in range(2):
        d = FakeWritable()
        ex = core.Executor(d, apply=True, log_path=str(log))
        ex.do("deactivate-user", d.deactivate, "bob", user="bob")
    e = _entries(log)
    assert all(x.get("run_id") for x in e) and [x["seq"] for x in e] == [1, 1, 1, 1]
    assert e[0]["run_id"] == e[1]["run_id"] != e[2]["run_id"] == e[3]["run_id"]


def test_applied_line_write_failure_marks_change_as_made(tmp_path, monkeypatch):
    log = tmp_path / "a.json"
    real = auditlog.record

    def flaky(path, event, *a, **k):
        if event == "applied":
            raise OSError("disk full")
        return real(path, event, *a, **k)
    monkeypatch.setattr(auditlog, "record", flaky)
    d = FakeWritable()
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(core.PartialFailure) as ei:
        ex.do("deactivate-user", d.deactivate, "bob", user="bob")
    intent, fail = _entries(log)
    assert fail["stage"] == "applied_log" and fail["change_applied"] is True
    assert fail["applied_before_failure"] == 1 == ei.value.applied
    assert fail["seq"] == intent["seq"] and fail["run_id"] == intent["run_id"]


def test_change_failure_stage_not_applied(tmp_path):
    d = FailingWritable(fail_at=0)
    log = tmp_path / "a.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(core.PartialFailure):
        ex.do("deactivate-user", d.deactivate, "bob", user="bob")
    fail = _entries(log)[-1]
    assert fail["stage"] == "change" and fail["change_applied"] is False


def test_interrupt_during_crowd_call_logs_change_applied_unknown(tmp_path):
    class Interrupting(FakeWritable):
        def deactivate(self, u):
            raise KeyboardInterrupt
    d = Interrupting()
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(KeyboardInterrupt):
        core.fix(core.audit(d, 90, NOW), ex)
    failed = _entries(log)[-1]
    assert failed["event"] == "failed" and failed["stage"] == "change"
    assert failed["change_applied"] is None


def test_ordinary_crowd_error_logs_change_applied_false(tmp_path):
    class Broken(FakeWritable):
        def deactivate(self, u):
            raise RuntimeError("boom")
    d = Broken()
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(core.PartialFailure):
        core.fix(core.audit(d, 90, NOW), ex)
    assert _entries(log)[-1]["change_applied"] is False


@pytest.mark.parametrize("name", ["ts"])
def test_record_rejects_reserved_field_names(tmp_path, name):
    log = tmp_path / "audit.json"
    with pytest.raises(ValueError, match="reserved"):
        auditlog.record(str(log), "applied", "x", {}, **{name: "forged"})
    assert not log.exists()


def test_version_is_0_2_0():
    import crowdkeeper
    assert crowdkeeper.__version__ == "0.2.0"
