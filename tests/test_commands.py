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
    assert len(entries) == len(d.calls) == 10
    assert all("ts" in e for e in entries)


def test_auditlog_drops_passwords(tmp_path):
    p = tmp_path / "x.json"
    auditlog.record(str(p), "create-user", user="u", password="hunter2")
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
