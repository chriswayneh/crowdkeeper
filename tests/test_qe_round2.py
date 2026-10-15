"""QE round 2 (PR #2 at e51abc6) and Red Team items. Each test failed before its fix."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import requests

from crowdkeeper import auditlog, core
from crowdkeeper.cli import main
from crowdkeeper.client import CrowdClient, CrowdError, check_url
from crowdkeeper.demo import DemoDirectory

ROOT = Path(__file__).resolve().parents[1]
COLS = ["action", "username", "display_name", "email", "groups"]


def _entries(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines()]


# ---- 1: blank groups cell never strips a mover ---------------------------------------------

@pytest.mark.parametrize("cell", ["", " ", "   ", ";", " ; ;", ";;"])
def test_item1_blank_groups_cell_leaves_mover_alone(cell):
    d = DemoDirectory()
    rows = [{"action": "mover", "username": "bob", "display_name": "", "email": "",
             "groups": cell}]
    assert core.jml(d, rows, core.Executor(d), COLS) == []


@pytest.mark.parametrize("cell", ["-", "none", "NONE", " None "])
def test_item1_explicit_none_removes_all_groups(cell):
    d = DemoDirectory()
    rows = [{"action": "mover", "username": "bob", "groups": cell}]
    plan = core.jml(d, rows, core.Executor(d), ["action", "username", "groups"])
    assert sorted((p["action"], p["group"]) for p in plan) == [
        ("remove-from-group", "bitbucket-users"), ("remove-from-group", "jira-users")]


def test_item1_none_mixed_with_groups_is_a_line_error():
    d = DemoDirectory()
    rows = [{"action": "mover", "username": "bob", "groups": "jira-users"},
            {"action": "mover", "username": "bob", "groups": "-;jira-users"}]
    with pytest.raises(ValueError, match="line 3"):
        core.jml(d, rows, core.Executor(d), ["action", "username", "groups"])


def test_item1_cli_blank_cell_plans_nothing_and_dash_removes(tmp_path, capsys):
    p = tmp_path / "j.csv"
    p.write_text("action,username,display_name,email,groups\nmover,bob,,,\nmover,alice,,, ; \n")
    assert main(["--demo", "jml", str(p), "-o", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    p.write_text("action,username,display_name,email,groups\nmover,bob,,,-\n")
    assert main(["--demo", "jml", str(p), "-o", "json"]) == 0
    assert {x["group"] for x in json.loads(capsys.readouterr().out)} == {
        "jira-users", "bitbucket-users"}


# ---- 2: password scrubbing does not over-mask ----------------------------------------------

def test_item2_short_password_not_masked_inside_words(monkeypatch):
    monkeypatch.setenv("CROWD_APP_PASSWORD", "us")
    msg = "GET /rest/usermanagement/1/user -> HTTP 404 status"
    assert auditlog.scrub(msg) == msg


def test_item2_short_password_still_masked_as_whole_token(monkeypatch):
    monkeypatch.setenv("CROWD_APP_PASSWORD", "pw1")
    assert auditlog.scrub("bad password pw1 rejected") == "bad password *** rejected"
    assert auditlog.scrub("https://app:pw1@crowd/x") == "https://***@crowd/x"


def test_item2_long_password_masked_anywhere(monkeypatch):
    monkeypatch.setenv("CROWD_APP_PASSWORD", "Sup3rSecret!")
    assert "Sup3rSecret" not in auditlog.scrub("xxSup3rSecret!yy and ?p=Sup3rSecret!")


# ---- 3: README example shows change_applied null -------------------------------------------

def test_item3_readme_failed_example_shows_change_applied_null():
    lines = [x for x in (ROOT / "README.md").read_text().splitlines()
             if x.startswith('{"ts"')]
    failed = [json.loads(x) for x in lines if '"event": "failed"' in x]
    assert failed and failed[0]["stage"] == "change" and failed[0]["change_applied"] is None


# ---- 4: Ctrl-C during the applied-line write ------------------------------------------------

def test_item4_interrupt_during_applied_write_logs_applied_log(tmp_path, monkeypatch):
    log = tmp_path / "a.json"
    real = auditlog.record
    hit = []

    def interrupting(path, event, *a, **k):
        if event == "applied" and not hit:
            hit.append(1)
            raise KeyboardInterrupt
        return real(path, event, *a, **k)
    monkeypatch.setattr(auditlog, "record", interrupting)
    d = DemoDirectory()
    d.writable, calls = True, []
    ex = core.Executor(d, apply=True, log_path=str(log))
    with pytest.raises(KeyboardInterrupt):
        ex.do("deactivate-user", lambda u: calls.append(u), "bob", user="bob")
    intent, fail = _entries(log)
    assert calls == ["bob"] and intent["event"] == "intent"
    assert fail["event"] == "failed" and fail["stage"] == "applied_log"
    assert fail["change_applied"] is True and fail["applied_before_failure"] == 1
    assert fail["error"].startswith("KeyboardInterrupt")


# ---- 5: ruff clean with a project config ----------------------------------------------------

def test_item5_pyproject_has_ruff_config():
    assert "[tool.ruff]" in (ROOT / "pyproject.toml").read_text()


@pytest.mark.skipif(not shutil.which("ruff"), reason="ruff not installed")
def test_item5_ruff_check_clean():
    r = subprocess.run(["ruff", "check", "--no-cache", str(ROOT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---- 6: CHANGELOG has no blank line inside a list --------------------------------------------

def test_item6_changelog_no_blank_line_between_list_items():
    lines = (ROOT / "CHANGELOG.md").read_text().splitlines()
    for i in range(1, len(lines) - 1):
        if lines[i] == "":
            assert not (lines[i - 1].startswith(("- ", "  ")) and lines[i + 1].startswith("- ")), \
                f"stray blank line at CHANGELOG.md:{i + 1}"


# ---- 7: client.py branch coverage (mocked HTTP) ---------------------------------------------

class Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data
        self.content = b"" if data is None else json.dumps(data).encode()

    def json(self):
        return self._data


@pytest.fixture
def client(monkeypatch):
    c = CrowdClient("https://crowd.example.com/crowd/", "app", "pw")
    calls = []
    script = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return script.pop(0) if script else Resp(204)
    monkeypatch.setattr(c.s, "request", fake)
    return c, calls, script


def test_item7_req_url_auth_timeout_and_empty_body(client):
    c, calls, _ = client
    assert c._req("GET", "/x", params={"a": 1}) is None
    _, url, kw = calls[0]
    assert url == "https://crowd.example.com/crowd/rest/usermanagement/1/x"
    assert kw["timeout"] == 30 and c.s.auth == ("app", "pw")
    assert c.s.headers["Accept"] == "application/json"


def test_item7_req_http_error_carries_status(client):
    c, _, script = client
    script.append(Resp(404, {"reason": "nope"}))
    with pytest.raises(CrowdError) as ei:
        c._req("GET", "/user")
    assert ei.value.status == 404 and "HTTP 404" in str(ei.value)


def test_item7_search_paginates(client, monkeypatch):
    c, _, _ = client
    pages = [{"users": [{"name": f"u{i}"} for i in range(1000)]}, {"users": [{"name": "z"}]}]
    seen = []

    def fake(method, path, **kw):
        seen.append(kw["params"]["start-index"])
        return pages[len(seen) - 1]
    monkeypatch.setattr(c, "_req", fake)
    assert len(c._search("user")) == 1001 and seen == [0, 1000]


@pytest.mark.parametrize("data,expected", [
    (None, None), ({}, None), ({"attributes": [{"name": "other", "values": ["1"]}]}, None),
    ({"attributes": [{"name": "lastAuthenticated", "values": []}]}, None),
    ({"attributes": [{"name": "lastAuthenticated", "values": ["1760486400000"]}]},
     "2025-10-15")])
def test_item7_last_login(client, monkeypatch, data, expected):
    c, _, _ = client
    monkeypatch.setattr(c, "_req", lambda *a, **k: data)
    got = c._last_login("bob")
    assert (got and got.date().isoformat()) == expected


def test_item7_users_and_groups(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(c, "_search", lambda e: [
        {"name": "bob", "display-name": "Bob", "email": "b@x", "active": False,
         "created-date": 1760486400000}, {"name": "amy"}] if e == "user" else
        [{"name": "z"}, {"name": "a"}])
    monkeypatch.setattr(c, "_last_login", lambda n: None)
    monkeypatch.setattr(c, "_direct_groups", lambda n: ["g"])
    bob, amy = c.users()
    assert (bob.active, bob.created.year, amy.active, amy.created) == (False, 2025, True, None)
    assert c.groups() == ["a", "z"]


def test_item7_writes_send_expected_requests(client):
    c, calls, script = client
    c.add_user("neo", "Neo Anderson", "n@x", password="s3cret-pass")
    c.add_user("trin")
    c.add_to_group("neo", "hr")
    c.remove_from_group("neo", "hr")
    script.append(Resp(200, {"name": "neo", "active": True}))
    c.deactivate("neo")
    body = calls[0][2]["json"]
    assert (body["first-name"], body["last-name"], body["password"]) == (
        "Neo", "Anderson", {"value": "s3cret-pass"})
    assert calls[1][2]["json"]["first-name"] == "trin" and "password" not in calls[1][2]["json"]
    assert calls[2][0] == "POST" and calls[2][2]["json"] == {"name": "hr"}
    assert calls[3][0] == "DELETE" and calls[3][2]["params"]["groupname"] == "hr"
    assert calls[-1][0] == "PUT" and calls[-1][2]["json"]["active"] is False


def test_item7_missing_settings_and_bad_url():
    with pytest.raises(CrowdError, match="Set CROWD_URL"):
        CrowdClient("", "app", "pw")
    with pytest.raises(CrowdError, match="not a valid URL"):
        check_url("https://[::1")


def test_item7_from_env(monkeypatch):
    monkeypatch.setenv("CROWD_URL", "https://crowd.example.com")
    monkeypatch.setenv("CROWD_APP", "app")
    monkeypatch.setenv("CROWD_APP_PASSWORD", "pw")
    assert CrowdClient.from_env().url.startswith("https://crowd.example.com/rest")


# ---- 8: Red Team -----------------------------------------------------------------------------

def test_item8_requests_floor_is_2_32_4():
    assert re.search(r'"requests>=2\.32\.4"', (ROOT / "pyproject.toml").read_text())
    assert tuple(int(x) for x in requests.__version__.split(".")[:3]) >= (2, 32, 4)


@pytest.mark.parametrize("url", ["http://localhost:8095", "http://127.0.0.1", "http://[::1]:8095",
                                 "http://crowd.example.com"])
def test_item8_any_http_refused_without_insecure(url):
    with pytest.raises(CrowdError, match="--insecure"):
        CrowdClient(url, "app", "pw")


@pytest.mark.parametrize("url", ["http://localhost:8095", "http://crowd.example.com"])
def test_item8_insecure_allows_http_with_warning(url, caplog):
    CrowdClient(url, "app", "pw-not-logged", insecure=True)
    assert "insecure" in caplog.text.lower() and "pw-not-logged" not in caplog.text


def test_item8_insecure_never_allows_credentials_or_other_schemes():
    with pytest.raises(CrowdError, match="credentials"):
        CrowdClient("http://a:b@localhost", "app", "pw", insecure=True)
    with pytest.raises(CrowdError):
        CrowdClient("ftp://crowd.example.com", "app", "pw", insecure=True)


def test_item8_cli_insecure_flag(monkeypatch, capsys):
    monkeypatch.setenv("CROWD_URL", "http://localhost:8095")
    monkeypatch.setenv("CROWD_APP", "app")
    monkeypatch.setenv("CROWD_APP_PASSWORD", "pw")
    assert main(["audit"]) == 1
    assert "--insecure" in capsys.readouterr().err
    monkeypatch.setattr(CrowdClient, "users", lambda self: [])
    monkeypatch.setattr(CrowdClient, "groups", lambda self: [])
    assert main(["--insecure", "audit", "-o", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_item8_security_md():
    t = (ROOT / "SECURITY.md").read_text()
    for s in ("Supported versions", "0.2", "private vulnerability reporting", "Scope"):
        assert s in t
    assert "SECURITY.md" in (ROOT / "README.md").read_text()
    assert "--insecure" in (ROOT / "README.md").read_text()
    assert "2.32.4" in (ROOT / "CHANGELOG.md").read_text()


def test_item2_short_password_masked_next_to_punctuation(monkeypatch):
    monkeypatch.setenv("CROWD_APP_PASSWORD", "pw1")
    for raw in ("password pw1.", "pw1-rejected", "x=_pw1_", "'pw1'", "(pw1)"):
        assert "pw1" not in auditlog.scrub(raw), raw
    assert auditlog.scrub("pw12 apw1") == "pw12 apw1"  # different alphanumeric tokens
