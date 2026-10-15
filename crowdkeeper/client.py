"""Thin client for the Crowd REST API (/rest/usermanagement/1) using application auth."""

import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from .models import User

log = logging.getLogger("crowdkeeper")
BASE = "/rest/usermanagement/1"


class CrowdError(RuntimeError):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status  # HTTP status, when Crowd answered


def check_url(url, insecure=False):
    """Require https and no credentials in the URL. Plain http (any host, localhost
    included) only with insecure=True (the --insecure flag)."""
    try:
        u = urlsplit(url)
        host = u.hostname
    except ValueError:
        raise CrowdError("CROWD_URL is not a valid URL") from None
    if u.username or u.password or "@" in u.netloc:
        raise CrowdError("CROWD_URL must not contain credentials; use CROWD_APP and CROWD_APP_PASSWORD")
    if u.scheme == "https" and host:
        return
    if u.scheme == "http" and host and insecure:
        log.warning("--insecure: CROWD_URL is plain http; the application password is sent unencrypted")
        return
    raise CrowdError(
        "CROWD_URL must be https:// so the application password is never sent "
        "unencrypted (pass --insecure to allow plain http, e.g. a local test server)"
    )


def _items(d, key, what):
    """Return d[key] as a list of objects that each have a string "name", or raise CrowdError:
    a malformed answer must never read as an empty (clean) result."""
    items = d.get(key) if isinstance(d, dict) else None
    if not isinstance(items, list) or not all(
        isinstance(x, dict) and isinstance(x.get("name"), str) for x in items
    ):
        raise CrowdError(f"unexpected Crowd response for {what}: expected a {key!r} list of named objects")
    return items


_MAX_MS = 253402300799999  # 9999-12-31T23:59:59.999Z


def _ms(v, what):
    """A Crowd millisecond timestamp (int, or a decimal string for attribute values) as UTC datetime."""
    if isinstance(v, str) and v.isascii() and v.isdigit():
        v = int(v)
    if type(v) is not int or not 0 <= v <= _MAX_MS:
        raise CrowdError(f"unexpected Crowd response for {what}: not a valid timestamp")
    return datetime.fromtimestamp(v / 1000, tz=timezone.utc)


def _str(u, key, what):
    v = u.get(key, "")
    if not isinstance(v, str):
        raise CrowdError(f"unexpected Crowd response for {what}: {key!r} is not a string")
    return v


class CrowdClient:
    writable = True

    def __init__(self, url, app, password, timeout=30, insecure=False):
        if not (url and app and password):
            raise CrowdError("Set CROWD_URL, CROWD_APP and CROWD_APP_PASSWORD (or use --demo).")
        check_url(url, insecure)
        self.url = url.rstrip("/") + BASE
        self.s = requests.Session()
        self.s.auth = (app, password)  # never logged
        self.s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.timeout = timeout

    @classmethod
    def from_env(cls, insecure=False):
        return cls(
            os.environ.get("CROWD_URL"),
            os.environ.get("CROWD_APP"),
            os.environ.get("CROWD_APP_PASSWORD"),
            insecure=insecure,
        )

    def _req(self, method, path, **kw):
        log.debug("%s %s params=%s", method, path, kw.get("params"))
        # never follow redirects: a 3xx (e.g. to a login page) must not count as success
        r = self.s.request(method, self.url + path, timeout=self.timeout, allow_redirects=False, **kw)
        if not 200 <= r.status_code < 300:
            raise CrowdError(f"{method} {path} -> HTTP {r.status_code}", r.status_code)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:  # e.g. an HTML login page served with 200
            msg = f"unexpected Crowd response for {method} {path}: not JSON"
            raise CrowdError(msg, r.status_code) from None

    def _search(self, entity):
        out, start = [], 0
        while True:
            d = self._req(
                "GET",
                "/search",
                params={"entity-type": entity, "expand": entity, "start-index": start, "max-results": 1000},
            )
            items = _items(d, entity + "s", f"{entity} search")
            out += items
            if len(items) < 1000:
                return out
            start += 1000

    def _last_login(self, name):
        d = self._req("GET", "/user/attribute", params={"username": name})
        if d is None or (isinstance(d, dict) and "attributes" not in d):
            return None  # no attributes recorded: login activity unknown (flagged for review only)
        for a in _items(d, "attributes", f"attributes of {name}"):
            if a.get("name") == "lastAuthenticated" and a.get("values"):
                return _ms(a["values"][0], f"lastAuthenticated of {name}")
        return None

    def _direct_groups(self, name, page=1000):
        out, start = [], 0
        while True:
            d = self._req(
                "GET",
                "/user/group/direct",
                params={"username": name, "start-index": start, "max-results": page},
            )
            items = _items(d, "groups", f"groups of {name}")
            out += [x["name"] for x in items]
            if len(items) < page:
                return sorted(out)
            start += page

    def users(self):
        res = []
        for u in self._search("user"):
            n = u["name"]
            what = f"user {n}"
            if not isinstance(u.get("active"), bool):  # no default: a missing flag must not read as active
                raise CrowdError(f"unexpected Crowd response for {what}: 'active' is not true/false")
            created = u.get("created-date")
            res.append(
                User(
                    n,
                    _str(u, "display-name", what),
                    _str(u, "email", what),
                    u["active"],
                    self._last_login(n),
                    self._direct_groups(n),
                    None if created is None else _ms(created, f"created-date of {n}"),
                )
            )
        return sorted(res, key=lambda u: u.name)  # stable order: the drift check compares plans

    def groups(self):
        return sorted(g["name"] for g in self._search("group"))

    def add_user(self, name, display_name="", email="", password=None):
        first, _, last = display_name.partition(" ")
        body = {
            "name": name,
            "first-name": first or name,
            "last-name": last or name,
            "display-name": display_name or name,
            "email": email,
            "active": True,
        }
        if password:
            body["password"] = {"value": password}
        self._req("POST", "/user", json=body)

    def add_to_group(self, user, group):
        self._req("POST", "/user/group/direct", params={"username": user}, json={"name": group})

    def remove_from_group(self, user, group):
        self._req("DELETE", "/user/group/direct", params={"username": user, "groupname": group})

    def deactivate(self, user):
        # Send back only the identity fields Crowd requires plus active=False, not the whole
        # fetched entity (attributes, password link, expand data). Crowd has no ETag/If-Match
        # for users, so a profile edit landing between this GET and PUT can still be overwritten.
        u = self._req("GET", "/user", params={"username": user})
        if not isinstance(u, dict) or u.get("name") != user:
            raise CrowdError(f"unexpected Crowd response for user {user!r}; not deactivated")
        # Crowd's PUT /user overwrites the profile fields, so echo every one back unchanged;
        # never default a missing one to "" (that would blank it in Crowd).
        fields = ("name", "first-name", "last-name", "display-name", "email")
        if not all(isinstance(u.get(k), str) for k in fields):
            raise CrowdError(f"incomplete Crowd profile for user {user!r}; not deactivated")
        body = {k: u[k] for k in fields}
        body["active"] = False
        self._req("PUT", "/user", params={"username": user}, json=body)
