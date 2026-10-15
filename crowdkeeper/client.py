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
        raise CrowdError("CROWD_URL must not contain credentials; use CROWD_APP and "
                         "CROWD_APP_PASSWORD")
    if u.scheme == "https" and host:
        return
    if u.scheme == "http" and host and insecure:
        log.warning("--insecure: CROWD_URL is plain http; the application password is sent "
                    "unencrypted")
        return
    raise CrowdError("CROWD_URL must be https:// so the application password is never sent "
                     "unencrypted (pass --insecure to allow plain http, e.g. a local test server)")


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
        return cls(os.environ.get("CROWD_URL"), os.environ.get("CROWD_APP"),
                   os.environ.get("CROWD_APP_PASSWORD"), insecure=insecure)

    def _req(self, method, path, **kw):
        log.debug("%s %s params=%s", method, path, kw.get("params"))
        r = self.s.request(method, self.url + path, timeout=self.timeout, **kw)
        if r.status_code >= 400:
            raise CrowdError(f"{method} {path} -> HTTP {r.status_code}", r.status_code)
        return r.json() if r.content else None

    def _search(self, entity):
        out, start = [], 0
        while True:
            d = self._req("GET", "/search", params={"entity-type": entity, "expand": entity,
                                                    "start-index": start, "max-results": 1000})
            items = d.get(entity + "s", [])
            out += items
            if len(items) < 1000:
                return out
            start += 1000

    def _last_login(self, name):
        d = self._req("GET", "/user/attribute", params={"username": name})
        for a in (d or {}).get("attributes", []):
            if a.get("name") == "lastAuthenticated" and a.get("values"):
                return datetime.fromtimestamp(int(a["values"][0]) / 1000, tz=timezone.utc)
        return None

    def _direct_groups(self, name, page=1000):
        out, start = [], 0
        while True:
            d = self._req("GET", "/user/group/direct", params={
                "username": name, "start-index": start, "max-results": page}) or {}
            items = d.get("groups", [])
            out += [x["name"] for x in items]
            if len(items) < page:
                return sorted(out)
            start += page

    def users(self):
        res = []
        for u in self._search("user"):
            n = u["name"]
            created = u.get("created-date")
            res.append(User(n, u.get("display-name", ""), u.get("email", ""), u.get("active", True),
                            self._last_login(n), self._direct_groups(n),
                            None if created is None else
                            datetime.fromtimestamp(int(created) / 1000, tz=timezone.utc)))
        return res

    def groups(self):
        return sorted(g["name"] for g in self._search("group"))

    def add_user(self, name, display_name="", email="", password=None):
        first, _, last = display_name.partition(" ")
        body = {"name": name, "first-name": first or name, "last-name": last or name,
                "display-name": display_name or name, "email": email, "active": True}
        if password:
            body["password"] = {"value": password}
        self._req("POST", "/user", json=body)

    def add_to_group(self, user, group):
        self._req("POST", "/user/group/direct", params={"username": user}, json={"name": group})

    def remove_from_group(self, user, group):
        self._req("DELETE", "/user/group/direct", params={"username": user, "groupname": group})

    def deactivate(self, user):
        u = self._req("GET", "/user", params={"username": user})
        u["active"] = False
        self._req("PUT", "/user", params={"username": user}, json=u)
