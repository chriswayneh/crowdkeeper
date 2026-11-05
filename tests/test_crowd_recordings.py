"""Exercise the Crowd client against sanitized REST response fixtures."""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from crowdkeeper.client import CrowdClient

FIXTURES = Path(__file__).parent / "fixtures" / "crowd"


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class _RecordedResponse:
    status_code = 200

    def __init__(self, body):
        self.content = body.encode("utf-8")
        self._body = body

    def json(self):
        return json.loads(self._body)


def _replay(monkeypatch, client, exchanges):
    remaining = iter(exchanges)
    seen = []

    def request(method, url, **kwargs):
        expected_method, expected_path, expected_params, response_file = next(remaining)
        parsed = urlsplit(url)
        base_path = urlsplit(client.url).path
        actual = (method, parsed.path.removeprefix(base_path), kwargs.get("params"))
        expected = (expected_method, expected_path, expected_params)
        assert actual == expected
        seen.append(actual)
        return _RecordedResponse(_fixture(response_file))

    monkeypatch.setattr(client.s, "request", request)
    return seen, remaining


def test_users_and_groups_from_crowd_response_fixtures(monkeypatch):
    client = CrowdClient("https://crowd.example.test", "app", "secret")
    exchanges = [
        (
            "GET",
            "/search",
            {
                "entity-type": "user",
                "expand": "user.attributes",
                "start-index": 0,
                "max-results": 1000,
            },
            "search-users-expanded.json",
        ),
        (
            "GET",
            "/user/group/direct",
            {"username": "alice", "start-index": 0, "max-results": 1000},
            "direct-groups-alice.json",
        ),
        (
            "GET",
            "/user/group/direct",
            {"username": "bob", "start-index": 0, "max-results": 1000},
            "direct-groups-bob.json",
        ),
        (
            "GET",
            "/search",
            {
                "entity-type": "group",
                "expand": "group",
                "start-index": 0,
                "max-results": 1000,
            },
            "search-groups.json",
        ),
    ]
    seen, remaining = _replay(monkeypatch, client, exchanges)

    users = client.users()
    assert [(u.name, u.active, u.last_login, u.groups) for u in users] == [
        (
            "alice",
            True,
            datetime(2025, 10, 15, tzinfo=timezone.utc),
            ["crowd-users", "jira-users"],
        ),
        ("bob", False, None, []),
    ]
    assert client.groups() == ["crowd-users", "jira-users"]
    assert len(seen) == 4  # no per-user /user/attribute requests
    assert list(remaining) == []


def test_last_login_from_crowd_attribute_response_fixture(monkeypatch):
    client = CrowdClient("https://crowd.example.test", "app", "secret")
    exchanges = [
        (
            "GET",
            "/user/attribute",
            {"username": "alice"},
            "user-attributes.json",
        )
    ]
    seen, remaining = _replay(monkeypatch, client, exchanges)

    assert client._last_login("alice") == datetime(2025, 10, 15, tzinfo=timezone.utc)
    assert len(seen) == 1
    assert list(remaining) == []
