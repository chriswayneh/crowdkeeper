"""v0.2.3 independent review: leaver deactivate failure, deactivate PUT contract, stable user order."""

import json

import pytest

from crowdkeeper import cli, core
from crowdkeeper.client import _MAX_MS, CrowdClient, CrowdError, _ms

from .test_commands import JmlWritable


class FailingDeactivate(JmlWritable):
    def deactivate(self, u):
        self.calls.append(("deactivate", u))
        raise CrowdError("PUT /user -> HTTP 500", 500)


def test_leaver_deactivate_failure_exits_1_skips_removals_and_logs(tmp_path, monkeypatch, capsys):
    d = FailingDeactivate()
    log = tmp_path / "a.json"
    rows = [{"action": "leaver", "username": "frank", "groups": ""}]
    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    args = type("A", (), {"apply": True, "output": "table", "log": str(log), "yes": True})()
    assert cli._run_plan(args, d, lambda ex: core.jml(d, rows, ex)) == 1
    assert d.calls == [("deactivate", "frank")]  # no group removal attempted after the failure
    entries = [json.loads(x) for x in log.read_text().splitlines()]
    assert [(e["event"], e["action"]) for e in entries] == [
        ("intent", "deactivate-user"),
        ("failed", "deactivate-user"),
    ]
    assert entries[1]["applied_before_failure"] == 0
    assert "0 change(s) were applied" in capsys.readouterr().err


_FULL = {"name": "bob", "first-name": "Bob", "last-name": "B", "display-name": "Bob B", "email": "b@x.io"}


@pytest.mark.parametrize("missing", ["first-name", "last-name", "display-name", "email"])
@pytest.mark.parametrize("bad", [None, 5, "drop"])
def test_deactivate_never_blanks_profile_fields(monkeypatch, missing, bad):
    # Crowd's PUT /user overwrites omitted/blank profile fields, so refuse rather than send "".
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    got = dict(_FULL)
    if bad == "drop":
        del got[missing]
    else:
        got[missing] = bad
    puts = []

    def fake(method, path, **kw):
        if method == "PUT":
            puts.append(kw)
        return dict(got)

    monkeypatch.setattr(c, "_req", fake)
    with pytest.raises(CrowdError):
        c.deactivate("bob")
    assert puts == []


def test_client_users_sorted_by_name(monkeypatch):
    # drift check compares plans in order; Crowd's search order is not guaranteed, so users() must be stable
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c, "_search", lambda e: [{"name": n, "active": True} for n in ("zed", "amy", "mo")])
    monkeypatch.setattr(c, "_last_login", lambda n: None)
    monkeypatch.setattr(c, "_direct_groups", lambda n: [])
    assert [u.name for u in c.users()] == ["amy", "mo", "zed"]


# QE round 1 on PR #6
def test_replan_error_is_reported_as_drift(tmp_path, monkeypatch, capsys):
    d = JmlWritable()
    rows = [{"action": "mover", "username": "bob", "groups": "jira-users"}]
    calls = []

    def planner(ex):
        calls.append(1)
        if len(calls) > 1:  # bob was deleted after the preview was confirmed
            d._users = [u for u in d._users if u.name != "bob"]
        return core.jml(d, rows, ex)

    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    log = tmp_path / "a.json"
    args = type("A", (), {"apply": True, "output": "table", "log": str(log), "yes": True})()
    assert cli._run_plan(args, d, planner) == 1
    assert d.calls == [] and not log.exists()
    assert "changed since the preview" in capsys.readouterr().err


def test_replan_jml_input_error_is_drift(tmp_path, monkeypatch, capsys):
    d = JmlWritable()
    calls = []

    def planner(ex):
        calls.append(1)
        if len(calls) > 1:
            raise core.JmlInputError("CSV line 2: mover bob: no such user")
        return core.jml(d, [{"action": "mover", "username": "bob", "groups": "jira-users"}], ex)

    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    args = type("A", (), {"apply": True, "output": "table", "log": str(tmp_path / "a"), "yes": True})()
    assert cli._run_plan(args, d, planner) == 1
    assert d.calls == []
    assert "changed since the preview" in capsys.readouterr().err


def _users_client(monkeypatch, user, attrs=None):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c, "_search", lambda e: [user])
    monkeypatch.setattr(c, "_direct_groups", lambda n: [])
    monkeypatch.setattr(c, "_req", lambda *a, **k: {"attributes": attrs or []})
    return c


_OK = {"name": "bob", "display-name": "Bob", "email": "b@x.io", "active": True, "created-date": 1760486400000}


@pytest.mark.parametrize(
    "patch",
    [
        {"active": None},
        {"active": "false"},
        {"active": 0},
        {"active": "drop"},
        {"display-name": 5},
        {"display-name": None},
        {"email": 5},
        {"email": ["x"]},
        {"created-date": "abc"},
        {"created-date": 1.5},
        {"created-date": True},
        {"created-date": -1},
        {"created-date": 10**30},
    ],
)
def test_users_bad_fields_raise(monkeypatch, patch):
    u = dict(_OK)
    for k, v in patch.items():
        if v == "drop":
            del u[k]
        else:
            u[k] = v
    with pytest.raises(CrowdError, match="unexpected Crowd response"):
        _users_client(monkeypatch, u).users()


@pytest.mark.parametrize("val", ["abc", "", "1e3", "-5", str(10**30), 10**30, None, True, 1.5])
def test_last_authenticated_bad_values_raise(monkeypatch, val):
    c = _users_client(monkeypatch, dict(_OK), [{"name": "lastAuthenticated", "values": [val]}])
    with pytest.raises(CrowdError, match="unexpected Crowd response"):
        c.users()


def test_good_fields_parse(monkeypatch):
    c = _users_client(monkeypatch, dict(_OK), [{"name": "lastAuthenticated", "values": ["1760486400000"]}])
    (u,) = c.users()
    assert (u.active, u.created.year, u.last_login.year, u.email) == (True, 2025, 2025, "b@x.io")


def test_users_bad_field_exits_1(monkeypatch, capsys):
    from crowdkeeper.cli import main

    u = dict(_OK, active="yes")
    c = _users_client(monkeypatch, u)
    monkeypatch.setattr(cli, "_dir", lambda a: (c, None))
    assert main(["audit"]) == 1
    assert "unexpected Crowd response" in capsys.readouterr().err


def test_req_2xx_non_json_raises(monkeypatch):
    class R:
        status_code, content = 200, b"<html>login</html>"

        def json(self):
            raise ValueError("Expecting value")

    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c.s, "request", lambda *a, **k: R())
    with pytest.raises(CrowdError, match=r"unexpected Crowd response.*GET /search"):
        c._req("GET", "/search")


def test_deactivate_rejects_complete_profile_of_wrong_user(monkeypatch):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    puts = []

    def fake(method, path, **kw):
        if method == "PUT":
            puts.append(kw)
        return dict(_FULL, name="alice")

    monkeypatch.setattr(c, "_req", fake)
    with pytest.raises(CrowdError):
        c.deactivate("bob")
    assert puts == []


# QE round 2 on PR #6


@pytest.mark.parametrize("values", [{"0": "1600000000000"}, 1600000000000, "1600000000000", [], None, ["x"]])
def test_last_authenticated_values_must_be_nonempty_list(monkeypatch, values):
    c = _users_client(monkeypatch, dict(_OK), [{"name": "lastAuthenticated", "values": values}])
    with pytest.raises(CrowdError, match="unexpected Crowd response"):
        c.users()


def test_ms_digit_string_capped():
    with pytest.raises(CrowdError, match="unexpected Crowd response"):
        _ms("9" * 5000, "t")
    with pytest.raises(CrowdError, match="unexpected Crowd response"):
        _ms("1" * 16, "t")


def test_recheck_crowd_error_not_reported_as_drift(monkeypatch, capsys, tmp_path):
    from crowdkeeper.cli import main

    calls = []
    good = [{"name": "lastAuthenticated", "values": ["1600000000000"]}]
    bad = [{"name": "lastAuthenticated", "values": ["9" * 5000]}]
    c = _users_client(monkeypatch, dict(_OK, active=False), good)
    c._direct_groups = lambda n: ["jira-users"]  # disabled user still in a group: fix plans a removal
    monkeypatch.setattr(
        c, "_req", lambda *a, **k: (calls.append(1), {"attributes": good if len(calls) < 2 else bad})[1]
    )
    monkeypatch.setattr(cli, "_dir", lambda a: (c, None))
    writes = []
    monkeypatch.setattr(c, "remove_from_group", lambda *a: writes.append(a))
    assert main(["fix", "--apply", "-y", "--log", str(tmp_path / "a")]) == 1
    err = capsys.readouterr().err
    assert "unexpected Crowd response" in err and "changed since the preview" not in err
    assert writes == []


def test_run_plan_reraises_crowd_error_even_if_value_error(monkeypatch, tmp_path):
    class Both(CrowdError, ValueError):
        pass

    d = JmlWritable()
    calls = []

    def planner(ex):
        calls.append(1)
        if len(calls) > 1:
            raise Both("boom")
        return core.jml(d, [{"action": "mover", "username": "bob", "groups": "jira-users"}], ex)

    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    args = type("A", (), {"apply": True, "output": "table", "log": str(tmp_path / "a"), "yes": True})()
    with pytest.raises(CrowdError):
        cli._run_plan(args, d, planner)
    assert d.calls == []


def test_ms_bounds_and_non_ascii_digits():
    with pytest.raises(CrowdError):
        _ms("١٢٣", "t")
    assert _ms(_MAX_MS, "t").year == 9999
    assert _ms(str(_MAX_MS), "t").year == 9999
    assert _ms(0, "t").year == 1970
    with pytest.raises(CrowdError):
        _ms(_MAX_MS + 1, "t")
    with pytest.raises(CrowdError):
        _ms(-1, "t")


def test_last_authenticated_uses_first_value(monkeypatch):
    attrs = [{"name": "lastAuthenticated", "values": ["1600000000000", "1700000000000"]}]
    (u,) = _users_client(monkeypatch, dict(_OK), attrs).users()
    assert u.last_login.year == 2020


def test_ms_max_boundary_pinned_to_literal():
    from datetime import datetime, timezone

    assert _ms(253402300799999, "t") == datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
    with pytest.raises(CrowdError):
        _ms(253402300800000, "t")


def test_ms_rejects_16_char_in_range_digit_string():
    with pytest.raises(CrowdError):
        _ms("0001600000000000", "t")
