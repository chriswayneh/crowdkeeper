"""Thin client for the Crowd REST API (/rest/usermanagement/1) using application auth."""
import logging
import os
from datetime import datetime, timezone

import requests

from .models import User

log = logging.getLogger("crowdkeeper")
BASE = "/rest/usermanagement/1"


class CrowdError(RuntimeError):
    pass


class CrowdClient:
    writable = True

    def __init__(self, url, app, password, timeout=30):
        if not (url and app and password):
            raise CrowdError("Set CROWD_URL, CROWD_APP and CROWD_APP_PASSWORD (or use --demo).")
        if not url.lower().startswith("https://"):
            log.warning("CROWD_URL is not https; the application password will be sent in clear text")
        self.url = url.rstrip("/") + BASE
        self.s = requests.Session()
        self.s.auth = (app, password)  # never logged
        self.s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.timeout = timeout

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("CROWD_URL"), os.environ.get("CROWD_APP"),
                   os.environ.get("CROWD_APP_PASSWORD"))

    def _req(self, method, path, **kw):
        log.debug("%s %s params=%s", method, path, kw.get("params"))
        r = self.s.request(method, self.url + path, timeout=self.timeout, **kw)
        if r.status_code >= 400:
            raise CrowdError(f"{method} {path} -> HTTP {r.status_code}")
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

    def users(self):
        res = []
        for u in self._search("user"):
            n = u["name"]
            g = self._req("GET", "/user/group/direct", params={"username": n}) or {}
            res.append(User(n, u.get("display-name", ""), u.get("email", ""), u.get("active", True),
                            self._last_login(n), sorted(x["name"] for x in g.get("groups", []))))
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
