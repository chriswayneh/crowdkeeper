import io
import json

import pytest

from crowdkeeper import cli, core
from crowdkeeper.cli import main

from .test_commands import FakeWritable

LEAVER = {"action": "leaver", "username": "frank", "groups": ""}
BAD_ROWS = [
    {"action": "promote", "username": "bob", "groups": ""},
    {"action": "mover", "username": "", "groups": "jira-users"},
    {"action": "mover", "username": "nobody-here", "groups": "jira-users"},
    {"action": "leaver", "username": "nobody-here", "groups": ""},
]


@pytest.mark.parametrize("bad", BAD_ROWS)
def test_api_valid_leaver_then_bad_row_changes_nothing(bad, tmp_path):
    d = FakeWritable()
    log = tmp_path / "audit.json"
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(ValueError, match="line 3"):
        core.jml(d, [LEAVER, bad], ex)
    assert d.calls == [] and ex.applied == 0 and not log.exists()


def test_api_reports_every_bad_row_with_line_numbers():
    d = FakeWritable()
    with pytest.raises(ValueError) as e:
        core.jml(d, [LEAVER, *BAD_ROWS], core.Executor(d, apply=True, log_path="/nonexistent/x"))
    msg = str(e.value)
    for n in (3, 4, 5, 6):
        assert f"line {n}:" in msg
    assert d.calls == []


def test_joiner_then_mover_of_same_new_user_is_valid():
    d = FakeWritable()
    rows = [
        {"action": "joiner", "username": "newbie", "groups": "jira-users"},
        {"action": "mover", "username": "newbie", "groups": "hr"},
    ]
    plan = core.jml(d, rows, core.Executor(d))
    assert plan[0]["action"] == "create-user"


@pytest.mark.parametrize("bad", BAD_ROWS)
def test_cli_valid_leaver_then_bad_row_changes_nothing(bad, tmp_path, monkeypatch, capsys):
    d = FakeWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    p = tmp_path / "jml.csv"
    p.write_text(
        "action,username,groups\n"
        f"{LEAVER['action']},{LEAVER['username']},\n"
        f"{bad['action']},{bad['username']},{bad['groups']}\n"
    )
    log = tmp_path / "audit.json"
    assert main(["jml", str(p), "--apply", "-y", "--log", str(log)]) == 1
    assert "line 3" in capsys.readouterr().err
    assert d.calls == [] and not log.exists()


class _Stdin(io.StringIO):
    def __init__(self, text, tty):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


def test_confirm_refuses_non_tty_stdin_even_with_yes_piped(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Stdin("yes\n", tty=False))
    assert cli._confirm(type("A", (), {"yes": False})(), 3) is False


def test_confirm_tty_yes_still_accepts(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Stdin("yes\n", tty=True))
    assert cli._confirm(type("A", (), {"yes": False})(), 3) is True


def test_cli_non_tty_without_y_aborts_nothing_changed(tmp_path, monkeypatch, capsys):
    d = FakeWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    monkeypatch.setattr("sys.stdin", _Stdin("yes\n", tty=False))
    p = tmp_path / "jml.csv"
    p.write_text("action,username,groups\nleaver,frank,\n")
    log = tmp_path / "audit.json"
    assert main(["jml", str(p), "--apply", "--log", str(log)]) == 0
    err = capsys.readouterr().err
    assert "Aborted, nothing changed." in err and "-y" in err
    assert d.calls == [] and not log.exists()


def test_version_is_0_2_1():
    import crowdkeeper

    assert crowdkeeper.__version__ == "0.2.1"
    assert json.dumps(crowdkeeper.__version__)
