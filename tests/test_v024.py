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
    a.write_text(json.dumps({"groups": {}}))

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.core, "diff_groups", boom)
    assert cli.main(["groups", "diff", str(a), str(a)]) == 130
    assert "Interrupted" in capsys.readouterr().err


@pytest.mark.parametrize("which", ["a", "b"])
def test_malformed_diff_file_is_named(which, tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"groups": {"g": ["u"]}}))
    bad = tmp_path / "bad_export.json"
    bad.write_text("{not json")
    files = [str(bad), str(good)] if which == "a" else [str(good), str(bad)]
    assert cli.main(["groups", "diff", *files]) == 1
    err = capsys.readouterr().err
    assert "bad_export" in err and "Traceback" not in err


GOOD = {"groups": {"g": ["u"]}}


@pytest.mark.parametrize(
    "shape",
    [[], "x", 1, None, {}, {"group": {}}, {"groups": []}, {"groups": {"g": "u"}}, {"groups": {"g": [1]}}],
)
@pytest.mark.parametrize("which", ["a", "b"])
def test_wrong_shape_diff_file_is_named(shape, which, tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(GOOD))
    bad = tmp_path / "shape_export.json"
    bad.write_text(json.dumps(shape))
    files = [str(bad), str(good)] if which == "a" else [str(good), str(bad)]
    assert cli.main(["groups", "diff", *files]) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"error: {bad}: not a valid groups export: ")
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "name,shown",
    [("a\x1b[31mb.json", "a\\u001b[31mb.json"), ("a\u202eb.json", "a\\u202eb.json")],
)
@pytest.mark.parametrize("content", ["{not json", json.dumps([])])
@pytest.mark.parametrize("which", ["a", "b"])
def test_diff_error_file_name_is_terminal_safe(name, shown, content, which, tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(GOOD))
    bad = tmp_path / name
    bad.write_text(content)
    files = [str(bad), str(good)] if which == "a" else [str(good), str(bad)]
    assert cli.main(["groups", "diff", *files]) == 1
    err = capsys.readouterr().err
    assert f"error: {tmp_path}/{shown}: not a valid groups export: " in err
    assert "\x1b" not in err and "\u202e" not in err
