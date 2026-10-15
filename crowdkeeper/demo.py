"""Built-in fake directory with planted problems. Read-only: any write raises."""
from datetime import datetime, timedelta, timezone

from .models import User

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

GROUPS = ["jira-users", "confluence-users", "jira-admins", "bitbucket-users",
          "finance", "hr", "contractors", "legacy-sox-approvers"]

# name, active, days since login (None = never), groups
_USERS = [
    ("alice", True, 1, ["jira-users", "confluence-users", "jira-admins"]),
    ("bob", True, 3, ["jira-users", "bitbucket-users"]),
    ("carol", True, 5, ["jira-users", "confluence-users", "finance"]),
    ("dave", True, 2, ["jira-users", "bitbucket-users"]),
    ("erin", True, 10, ["confluence-users", "hr"]),
    ("frank", True, 140, ["jira-users", "finance"]),
    ("grace", True, 7, ["jira-users", "confluence-users"]),
    ("heidi", True, 220, ["jira-users", "jira-admins"]),
    ("ivan", False, 300, ["jira-users", "bitbucket-users"]),
    ("judy", True, 4, ["confluence-users"]),
    ("mallory", False, 400, ["jira-admins", "finance"]),
    ("niaj", True, 12, ["jira-users", "contractors"]),
    ("olivia", True, None, []),
    ("peggy", True, 30, ["jira-users", "confluence-users"]),
    ("rupert", True, 95, ["contractors", "bitbucket-users"]),
    ("sybil", True, 6, ["hr", "confluence-users"]),
    ("trent", False, 180, ["contractors"]),
    ("uma", True, 8, ["jira-users"]),
    ("victor", True, 15, []),
    ("walter", True, 1, ["jira-users", "bitbucket-users", "confluence-users"]),
    ("xena", True, 45, ["finance"]),
    ("yusuf", True, 9, ["jira-users"]),
    ("zoe", True, 2, ["confluence-users"]),
    ("svc-backup", True, 365, []),
    ("old-intern", False, 500, []),
]


class DemoDirectory:
    writable = False

    def __init__(self):
        self._users = [User(n, n.replace("-", " ").title(), f"{n}@example.com", a,
                            None if d is None else NOW - timedelta(days=d), sorted(g))
                       for n, a, d, g in _USERS]

    def users(self):
        return [User(u.name, u.display_name, u.email, u.active, u.last_login, list(u.groups))
                for u in self._users]

    def groups(self):
        return sorted(GROUPS)

    def _nope(self, *a, **k):
        raise PermissionError("demo mode never writes")

    add_user = add_to_group = remove_from_group = deactivate = _nope
