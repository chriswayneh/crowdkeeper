"""Independent review of PR #4: real line numbers, exit 2 for row validation, terminal-safe output."""

import json

from crowdkeeper import cli, core
from crowdkeeper.cli import main

from .test_commands import FakeWritable

EVIL = "bo\x1b[31mb\u202e\u200b\u2028x"


def _jml(tmp_path, monkeypatch, text, *extra):
    d = FakeWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    p = tmp_path / "jml.csv"
    p.write_text(text)
    return main(["jml", str(p), *extra]), d


# (a) real file line numbers in later validation errors
def test_unknown_group_line_counts_blank_lines(tmp_path, monkeypatch, capsys):
    rc, _ = _jml(tmp_path, monkeypatch, "action,username,groups\n\n\nmover,bob,no-such-group\n")
    assert "line 4: unknown group" in capsys.readouterr().err


def test_missing_user_line_counts_blank_lines(tmp_path, monkeypatch, capsys):
    rc, _ = _jml(tmp_path, monkeypatch, "action,username,groups\nleaver,frank,\n\nleaver,ghost,\n")
    assert "line 4: leaver ghost: no such user" in capsys.readouterr().err


def test_line_numbers_count_leading_and_middle_blank_lines(tmp_path, monkeypatch, capsys):
    # blank lines both before the header and between rows
    rc, _ = _jml(tmp_path, monkeypatch, "\naction,username,groups\nleaver,frank,\n\n\nbogus,frank,\n")
    assert "line 6: unknown action" in capsys.readouterr().err


def test_read_returns_line_numbers(tmp_path):
    p = tmp_path / "j.csv"
    p.write_text("action,username\n\nleaver,frank\n\n\nleaver,bob\n")
    rows, cols, lines = cli._read_jml_csv(p, with_lines=True)
    assert lines == [3, 6]


# exit 2 for every input error, row validation included
def test_row_validation_error_exits_2(tmp_path, monkeypatch):
    rc, d = _jml(tmp_path, monkeypatch, "action,username,groups\nmover,bob,no-such-group\n", "--apply", "-y")
    assert rc == 2 and d.calls == []


def test_row_validation_error_is_value_error_subclass():
    assert issubclass(core.JmlInputError, ValueError)


# (b) terminal-safe plain table output
def test_table_neutralises_control_bidi_zero_width():
    out = core.fmt([{"user": EVIL, "group": "g\x00"}], ["user", "group"])
    for c in ("\x1b", "\u202e", "\u200b", "\u2028", "\x00"):
        assert c not in out
    assert "U+001B" in out and "U+202E" in out and "U+0000" in out


def test_table_header_and_widths_use_safe_text():
    out = core.fmt([{"user": "a\x1bb"}], ["user"])
    lines = out.splitlines()
    assert len(lines[1]) == len("aU+001Bb")


def test_csv_neutralises_control_chars():
    out = core.fmt([{"user": EVIL}], ["user"], "csv")
    assert "\x1b" not in out and "\u202e" not in out and "U+001B" in out


def test_json_escapes_and_round_trips():
    out = core.fmt([{"user": EVIL}], ["user"], "json")
    assert "\x1b" not in out and "\u202e" not in out
    assert json.loads(out)[0]["user"] == EVIL


def test_audit_table_cli_is_terminal_safe(monkeypatch, capsys):
    monkeypatch.setattr(
        core, "audit", lambda d, days, now: [{"type": "x", "subject": EVIL, "detail": "", "fix": ""}]
    )
    monkeypatch.setattr(cli, "_dir", lambda a: (None, None))
    assert main(["audit"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\u202e" not in out


def test_shared_helper_is_used():
    assert core.term_safe("a\x1bb\tc") == "aU+001Bb c"
