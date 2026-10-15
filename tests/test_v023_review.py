"""v0.2.3 independent review: leaver deactivate failure, deactivate PUT contract, stable user order."""

import json

import pytest

from crowdkeeper import cli, core
from crowdkeeper.client import CrowdClient, CrowdError

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
    monkeypatch.setattr(c, "_search", lambda e: [{"name": "zed"}, {"name": "amy"}, {"name": "mo"}])
    monkeypatch.setattr(c, "_last_login", lambda n: None)
    monkeypatch.setattr(c, "_direct_groups", lambda n: [])
    assert [u.name for u in c.users()] == ["amy", "mo", "zed"]
