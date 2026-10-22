"""v0.2.4: Ctrl-C outside apply exits 130 without a traceback; malformed diff files are named."""

import json

import pytest

import crowdkeeper
from crowdkeeper import cli


def test_version():
    assert crowdkeeper.__version__ == "0.2.4"


@pytest.mark.parametrize(
    "argv",
    [["--demo", "audit"], ["--demo", "report"], ["--demo", "groups", "export"], ["--demo", "fix"]],
)
def test_ctrl_c_outside_apply_exits_130(argv, monkeypatch, capsys):
    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_dir", boom)
    assert cli.main(argv) == 130
    err = capsys.readouterr().err
    assert "Interrupted" in err and "Traceback" not in err


def test_ctrl_c_in_groups_diff_exits_130(tmp_path, monkeypatch, capsys):
    a = tmp_path / "a.json"
    a.write_text("{}")

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.core, "diff_groups", boom)
    assert cli.main(["groups", "diff", str(a), str(a)]) == 130
    assert "Interrupted" in capsys.readouterr().err


@pytest.mark.parametrize("which", ["a", "b"])
def test_malformed_diff_file_is_named(which, tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"g": ["u"]}))
    bad = tmp_path / "bad_export.json"
    bad.write_text("{not json")
    files = [str(bad), str(good)] if which == "a" else [str(good), str(bad)]
    assert cli.main(["groups", "diff", *files]) == 1
    err = capsys.readouterr().err
    assert "bad_export" in err and "Traceback" not in err
