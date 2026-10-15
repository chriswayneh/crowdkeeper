"""QE round for PR #4: strict JML CSV loading and terminal/Markdown-safe report text."""

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from markdown_it import MarkdownIt

from crowdkeeper import cli, core
from crowdkeeper.cli import main

from .test_commands import FakeWritable

HDR = b"action,username,display_name,email,groups\n"


def _run(tmp_path, monkeypatch, data):
    d = FakeWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    p = tmp_path / "jml.csv"
    p.write_bytes(data)
    log = tmp_path / "audit.json"
    rc = main(["jml", str(p), "--apply", "-y", "--log", str(log)])
    return rc, d, log


# 1. BOM
def test_bom_csv_is_read(tmp_path):
    p = tmp_path / "b.csv"
    p.write_bytes(b"\xef\xbb\xbf" + HDR + b"leaver,frank,,,\n")
    rows, cols = cli._read_jml_csv(p)
    assert cols[0] == "action" and rows[0]["action"] == "leaver"


def test_bom_csv_applies(tmp_path, monkeypatch):
    rc, d, _ = _run(tmp_path, monkeypatch, b"\xef\xbb\xbf" + HDR + b"leaver,frank,,,\n")
    assert rc == 0 and d.calls


BAD = {
    # 2. non-UTF-8, with its line
    "nonutf8": (HDR + b"leaver,b\xff\xfeob,,,\n", "line 2"),
    # 3. control / format characters
    "nul": (HDR + b"leaver,bo\x00b,,,\n", "line 2"),
    "esc": (HDR + b"leaver,bo\x1bb,,,\n", "line 2"),
    "tab": (HDR + b"leaver,bob\t,,,\n", "line 2"),
    "c1": (HDR + "leaver,bo\u0085b,,,\n".encode(), "line 2"),
    "rlo": (HDR + "leaver,bo\u202eb,,,\n".encode(), "line 2"),
    "zwsp": (HDR + "leaver,bo\u200bb,,,\n".encode(), "line 2"),
    "lsep": (HDR + "leaver,bo\u2028b,,,\n".encode(), "line 2"),
    "newline-in-quotes": (HDR + b'leaver,"bo\nb",,,\n', "line 2"),
    "ctl-in-header": (b"action,user\x00name,groups\nleaver,bob,\n", "line 1"),
    # 4. structure
    "missing-required": (b"act,user\nleaver,bob\n", "line 1"),
    "extra": (HDR + b"joiner,n,N,n@x,jira-users,a,b\n", "line 2"),
    "short": (HDR + b"leaver\n", "line 2"),
    "empty": (b"", "no header"),
    "only-blank-lines": (b"\n\n", "no header"),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_bad_csv_exit_2_no_writes(name, tmp_path, monkeypatch, capsys):
    data, where = BAD[name]
    rc, d, log = _run(tmp_path, monkeypatch, data)
    err = capsys.readouterr().err
    assert rc == 2, err
    assert d.calls == [] and not log.exists()
    assert where in err


def test_short_row_line_number_counts_physical_lines(tmp_path, monkeypatch, capsys):
    rc, d, _ = _run(tmp_path, monkeypatch, HDR + b"\nleaver,frank,,,\n\nleaver\n")
    assert rc == 2 and d.calls == []
    assert "line 5" in capsys.readouterr().err


# 5. Markdown autolinks, _ and ~ (GFM-like render with linkify)
MD = MarkdownIt("gfm-like", {"linkify": True})
MD.enable(["linkify", "strikethrough"])
BAD_HTML = re.compile(r"<a |<img|<script|<em>|<strong>|<s>|<del>", re.IGNORECASE)


def _cell(s):
    return MD.render("| G | M |\n|---|---|\n| " + core.md_safe(s) + " | 1 |\n")


@pytest.mark.parametrize(
    "s",
    [
        "http://evil.example",
        "https://x.y/a",
        "www.evil.example",
        "a@evil.example",
        "_x_",
        "__x__",
        "~~x~~",
        "~x~",
    ],
)
def test_md_safe_neutralises_autolinks_and_emphasis(s):
    html = _cell(s)
    assert html.count("<td>") == 2 and not BAD_HTML.search(html), html


@settings(max_examples=500, deadline=None)
@given(st.text())
def test_md_safe_property_one_plain_cell(s):
    html = _cell(s)
    assert html.count("<td>") == 2 and not BAD_HTML.search(html), (s, html)


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=300))
def test_loader_never_crashes(b):
    import os
    import tempfile

    fd, p = tempfile.mkstemp(suffix=".csv")
    os.write(fd, b)
    os.close(fd)
    try:
        cli._read_jml_csv(p)
    except cli._CsvError:
        pass
    finally:
        os.unlink(p)


# 6. terminal-injection characters in report text
DANGEROUS = "\x1b[31m\x1b]8;;http://e\x07L\x1b]8;;\x07\u202e\u200b\u2028\u2029\x00\x85\x7f\ufeff"


@pytest.mark.parametrize("fn", [core.md_safe, core.md_code_safe])
def test_report_text_has_no_control_or_bidi_chars(fn):
    import unicodedata

    out = fn("a" + DANGEROUS + "b")
    bad = [c for c in out if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp")]
    assert bad == [], out
    assert "U+001B" in out and "U+202E" in out  # visible, not silently dropped


# 7. README release claim
def test_readme_does_not_claim_old_latest_release():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "README.md").read_text()
    assert "latest release is v0.2.0" not in text
