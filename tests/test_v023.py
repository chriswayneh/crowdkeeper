"""v0.2.3: verified Codex findings (leaver order, redirects, drift, deactivate body,
malformed responses, header names, report snapshot, direct-only docs)."""

import json
from pathlib import Path

import pytest

from crowdkeeper import cli, core
from crowdkeeper.cli import main
from crowdkeeper.client import CrowdClient, CrowdError

from .test_commands import JmlWritable

ROOT = Path(__file__).resolve().parent.parent


# 1. leavers are deactivated before their groups are removed
class FailingRemove(JmlWritable):
    def remove_from_group(self, u, g):
        self.calls.append(("remove", u, g))
        raise CrowdError("DELETE -> HTTP 500", 500)


def test_leaver_deactivated_first_in_plan():
    d = JmlWritable()
    plan = core.jml(d, [{"action": "leaver", "username": "frank", "groups": ""}], core.Executor(d))
    assert [p["action"] for p in plan] == ["deactivate-user", "remove-from-group", "remove-from-group"]


def test_leaver_group_removal_failure_leaves_account_deactivated(tmp_path):
    d = FailingRemove()
    ex = core.Executor(d, apply=True, log_path=str(tmp_path / "a.json"))
    with pytest.raises(core.PartialFailure):
        core.jml(d, [{"action": "leaver", "username": "frank", "groups": ""}], ex)
    assert d.calls[0] == ("deactivate", "frank")


# 2. redirects and non-2xx are failures, never "applied"
class _Resp:
    def __init__(self, status, content=b"", js=None):
        self.status_code, self.content, self._js = status, content, js

    def json(self):
        return self._js


def _client_with(monkeypatch, resp):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    seen = {}

    def req(method, url, **kw):
        seen.update(kw)
        return resp

    monkeypatch.setattr(c.s, "request", req)
    return c, seen


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 304, 100])
def test_req_rejects_redirect_and_non_2xx(monkeypatch, status):
    c, _ = _client_with(monkeypatch, _Resp(status))
    with pytest.raises(CrowdError) as e:
        c._req("DELETE", "/user/group/direct")
    assert e.value.status == status


def test_req_disables_redirects(monkeypatch):
    c, seen = _client_with(monkeypatch, _Resp(204))
    assert c._req("DELETE", "/x") is None
    assert seen.get("allow_redirects") is False


def test_req_2xx_json(monkeypatch):
    c, _ = _client_with(monkeypatch, _Resp(200, b"{}", {"a": 1}))
    assert c._req("GET", "/x") == {"a": 1}


# 3. drift between preview/confirm and apply aborts before any change
def test_apply_aborts_on_drift_and_changes_nothing(tmp_path, monkeypatch, capsys):
    d = JmlWritable()
    rows = [{"action": "mover", "username": "bob", "groups": "jira-users"}]
    calls = []

    def planner(ex):
        calls.append(1)
        if len(calls) > 1:  # directory changed after the preview was confirmed
            d._users = [u for u in d._users if u.name != "bob"] + [
                type(d._users[0])("bob", groups=["jira-users", "hr"])
            ]
        return core.jml(d, rows, ex)

    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    args = type("A", (), {"apply": True, "output": "table", "log": str(tmp_path / "a.json"), "yes": True})()
    assert cli._run_plan(args, d, planner) == 1
    assert d.calls == []
    assert "changed since the preview" in capsys.readouterr().err


def test_apply_without_drift_runs_confirmed_plan(tmp_path, monkeypatch):
    d = JmlWritable()
    rows = [{"action": "mover", "username": "bob", "groups": "jira-users"}]
    monkeypatch.setattr(cli, "_confirm", lambda a, n: True)
    args = type("A", (), {"apply": True, "output": "table", "log": str(tmp_path / "a.json"), "yes": True})()
    assert cli._run_plan(args, d, lambda ex: core.jml(d, rows, ex)) == 0
    assert d.calls == [("remove", "bob", "bitbucket-users")]


# 4. deactivate sends only the identity fields, never the whole fetched entity back
def test_deactivate_minimal_body(monkeypatch):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    sent = []
    full = {
        "name": "bob",
        "first-name": "Bob",
        "last-name": "B",
        "display-name": "Bob B",
        "email": "bob@example.com",
        "active": True,
        "attributes": {"attributes": [{"name": "x"}]},
        "password": {"link": {}},
        "expand": "attributes",
        "link": {"href": "x"},
        "key": "k",
    }

    def fake(method, path, **kw):
        sent.append((method, kw))
        return dict(full) if method == "GET" else None

    monkeypatch.setattr(c, "_req", fake)
    c.deactivate("bob")
    put = next(kw for m, kw in sent if m == "PUT")["json"]
    assert put == {
        "name": "bob",
        "first-name": "Bob",
        "last-name": "B",
        "display-name": "Bob B",
        "email": "bob@example.com",
        "active": False,
    }


@pytest.mark.parametrize("got", [None, [], {"name": "alice"}, "x"])
def test_deactivate_rejects_bad_or_mismatched_user(monkeypatch, got):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    puts = []

    def fake(method, path, **kw):
        if method == "PUT":
            puts.append(kw)
        return got

    monkeypatch.setattr(c, "_req", fake)
    with pytest.raises(CrowdError):
        c.deactivate("bob")
    assert puts == []


# 5. malformed responses raise CrowdError instead of looking empty
BAD = [None, [], {}, {"users": None}, {"users": {}}, {"users": [1]}, {"users": [{"x": 1}]}, "x"]


@pytest.mark.parametrize("resp", BAD)
def test_search_users_malformed(monkeypatch, resp):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c, "_req", lambda *a, **k: resp)
    with pytest.raises(CrowdError):
        c._search("user")


@pytest.mark.parametrize(
    "resp", [None, [], {}, {"groups": None}, {"groups": [1]}, {"groups": [{"name": 3}]}, "x"]
)
def test_direct_groups_malformed(monkeypatch, resp):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c, "_req", lambda *a, **k: resp)
    with pytest.raises(CrowdError):
        c._direct_groups("bob")


@pytest.mark.parametrize("resp", [[], {"attributes": None}, {"attributes": [1]}, "x"])
def test_last_login_malformed(monkeypatch, resp):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c, "_req", lambda *a, **k: resp)
    with pytest.raises(CrowdError):
        c._last_login("bob")


def test_valid_empty_results_still_ok(monkeypatch):
    c = CrowdClient("https://crowd.example.com", "app", "pw")
    monkeypatch.setattr(c, "_req", lambda *a, **k: {"users": [], "groups": [], "attributes": []})
    assert c._search("user") == [] and c._direct_groups("bob") == [] and c._last_login("bob") is None


# 6. header names are stripped and unknown columns rejected
def _jml(tmp_path, monkeypatch, text):
    d = JmlWritable()
    monkeypatch.setattr(cli, "_dir", lambda a: (d, None))
    p = tmp_path / "j.csv"
    p.write_text(text)
    return main(["jml", str(p), "-o", "json"])


def test_padded_groups_header_is_used(tmp_path, monkeypatch, capsys):
    assert _jml(tmp_path, monkeypatch, "action , username,groups \nmover,bob,jira-users\n") == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan == [{"action": "remove-from-group", "user": "bob", "group": "bitbucket-users"}]


@pytest.mark.parametrize(
    "hdr", ["action,username,group", "action,username,groups,notes", "action,username,Groups"]
)
def test_unknown_column_rejected(tmp_path, monkeypatch, capsys, hdr):
    n = hdr.count(",") + 1
    row = ",".join(["mover", "bob"] + ["x"] * (n - 2))
    assert _jml(tmp_path, monkeypatch, f"{hdr}\n{row}\n") == 2
    assert "unknown column" in capsys.readouterr().err


# 7. report reads the directory once
class Counting(JmlWritable):
    def __init__(self):
        super().__init__()
        self.n = {"users": 0, "groups": 0}

    def users(self):
        self.n["users"] += 1
        return super().users()

    def groups(self):
        self.n["groups"] += 1
        return super().groups()


def test_report_single_snapshot():
    d = Counting()
    core.report(d, 90, core.datetime(2026, 10, 1, tzinfo=core.timezone.utc))
    assert d.n == {"users": 1, "groups": 1}


# 8. docs say membership is direct-only
def test_readme_says_direct_membership_only():
    text = " ".join(ROOT.joinpath("README.md").read_text().lower().split())
    assert "direct group memberships only" in text
    assert "nested" in text
