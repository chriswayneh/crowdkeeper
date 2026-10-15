import io

import pytest

from crowdkeeper import cli, core
from crowdkeeper.cli import main

from .test_commands import FakeWritable


def _run(tmp_path, monkeypatch, text):
    d = FakeWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    p = tmp_path / "jml.csv"
    p.write_text(text)
    log = tmp_path / "audit.json"
    rc = main(["jml", str(p), "--apply", "-y", "--log", str(log)])
    return rc, d, log


BAD_HEADERS = [
    "action,username,groups,groups\nmover,alice,jira-users,\n",
    "action,username,groups,\nleaver,frank,,\n",
    "action,username,groups, \nleaver,frank,,x\n",
]


@pytest.mark.parametrize("text", BAD_HEADERS)
def test_duplicate_or_blank_header_rejected_exit_2(text, tmp_path, monkeypatch, capsys):
    rc, d, log = _run(tmp_path, monkeypatch, text)
    err = capsys.readouterr().err
    assert rc == 2
    assert "line 1" in err and "header" in err
    assert d.calls == [] and not log.exists()


def test_unclosed_quote_rejected_exit_2_with_line(tmp_path, monkeypatch, capsys):
    text = 'action,username,groups\nleaver,frank,\nleaver,bob,"jira-users\n'
    rc, d, log = _run(tmp_path, monkeypatch, text)
    err = capsys.readouterr().err
    assert rc == 2
    assert "line 3" in err
    assert d.calls == [] and not log.exists()


def test_garbage_after_quote_rejected_exit_2(tmp_path, monkeypatch, capsys):
    text = 'action,username,groups\nleaver,"frank"x,\n'
    rc, d, log = _run(tmp_path, monkeypatch, text)
    assert rc == 2
    assert "line 2" in capsys.readouterr().err
    assert d.calls == [] and not log.exists()


def test_valid_csv_still_applies(tmp_path, monkeypatch):
    rc, d, log = _run(tmp_path, monkeypatch, "action,username,groups\nleaver,frank,\n")
    assert rc == 0 and d.calls and log.exists()


@pytest.mark.parametrize("ch", list("[]()<>!*&"))
def test_md_safe_escapes_link_and_html_chars(ch):
    out = core.md_safe(f"a{ch}b")
    assert f"a{ch}b" not in out


def test_md_safe_neutralises_link_and_html():
    out = core.md_safe("[x](http://evil) <img src=x> a&b")
    assert "](" not in out and "<img" not in out and "&b" not in out
    assert "\\[x\\]\\(http://evil\\)" in out and "&lt;img" in out and "&amp;b" in out


def test_md_safe_keeps_existing_escapes():
    assert core.md_safe("a|b`c\nd") == "a\\|b'c d"


def test_piped_yes_without_y_does_not_apply(tmp_path, monkeypatch, capsys):
    class S(io.StringIO):
        def isatty(self):
            return False

    d = FakeWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    monkeypatch.setattr("sys.stdin", S("yes\n"))
    p = tmp_path / "jml.csv"
    p.write_text("action,username,groups\nleaver,frank,\n")
    assert main(["jml", str(p), "--apply", "--log", str(tmp_path / "l")]) == 2
    assert d.calls == []


def test_version_is_0_2_2():
    import crowdkeeper

    assert crowdkeeper.__version__ == "0.2.2"


VALID_CSVS = [
    "\ufeffaction,username,groups\nleaver,frank,\n",
    'action,username,groups\r\nmover,alice,"jira-users,confluence-users"\r\n',
    " action , username ,groups\nmover,alice,a;b\n\nleaver,frank\nmover,bob,x,extra\n",
    'action,username,groups\nmover,alice,"say ""hi"""\n',
]


@pytest.mark.parametrize("text", VALID_CSVS)
def test_strict_reader_matches_dictreader_for_valid_files(text, tmp_path):
    import csv

    p = tmp_path / "jml.csv"
    p.write_bytes(text.encode("utf-8"))
    with open(p, newline="") as f:
        r = csv.DictReader(f)
        expected = (list(r), r.fieldnames)
    assert cli._read_jml_csv(p) == expected


def test_version_compares_numerically():
    import crowdkeeper

    def as_tuple(v):
        return tuple(int(x) for x in v.split("."))

    assert as_tuple(crowdkeeper.__version__) >= (0, 2, 1)
    assert as_tuple("0.10.0") > as_tuple("0.2.1")


def test_report_code_span_subject_not_backslash_or_entity_escaped():
    out = core.md_code_safe("a[b](c)*!&<x>|`y\nz")
    assert "\\" not in out and "&amp;" not in out and "&lt;" not in out
    assert "`" not in out and "\n" not in out
    assert out == "a[b](c)*!&<x>|'y z"
