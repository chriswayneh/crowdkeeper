# crowdkeeper

Access hygiene and joiner/mover/leaver (JML) CLI for Atlassian Crowd admins. It talks to
Crowd's REST API (`/rest/usermanagement/1`) using application authentication.

## Quick start

```bash
pip install .            # Python 3.10+
crowdkeeper --demo audit # try it with the built-in fake directory, no server needed
```

Against a real Crowd server:

```bash
export CROWD_URL=https://crowd.example.com/crowd
export CROWD_APP=crowdkeeper
export CROWD_APP_PASSWORD=...   # never logged or written to the audit log
crowdkeeper audit --days 90
```

## Commands

| Command | What it does |
|---|---|
| `audit [--days N] [-o table\|json\|csv]` | Inactive users (no login in N days), active users with no groups, disabled users still in groups, empty groups |
| `groups export [-f FILE]` | Dump group membership as JSON |
| `groups diff A B` | Show access drift (granted/revoked/group added/removed) between two exports |
| `jml FILE.csv [--apply]` | Joiners (create + add groups), movers (set groups), leavers (strip groups + deactivate) |
| `fix [--apply]` | Apply the audit's recommended cleanups (deactivate inactive, strip groups from disabled users) |
| `report [-f FILE]` | One-page Markdown summary for auditors |

**Safety:** `jml` and `fix` are dry-run by default. Changes happen only with `--apply` plus a typed
`yes` confirmation (or `-y`). Every applied change is appended as a JSON line to the audit log
(`--log`, default `crowdkeeper-audit.json`). Password fields are never logged.

**Partial failures:** if a change fails partway through `jml --apply` or `fix --apply` (including
Ctrl-C), crowdkeeper stops at that change. Every change already applied is in the audit log, followed
by a `"action": "failed"` entry with the failed change, the error (secrets scrubbed), the count of
changes applied before it, and a UTC timestamp. The command then exits with status 1. Nothing is
rolled back automatically; use the log to finish or reverse the run.

**Demo mode:** `--demo` or `CROWDKEEPER_DEMO=1` uses a built-in directory of 25 users and 8 groups with
planted problems. Demo mode never writes anything to a directory; `--apply` falls back to a dry run.

JML CSV format (`groups` separated by `;` or spaces; for movers it's the full target set):

```csv
action,username,display_name,email,groups
joiner,newhire,New Hire,newhire@example.com,jira-users;confluence-users
mover,bob,,,jira-users;confluence-users
leaver,frank,,,
```

## Sample output (real demo runs)

```text
$ crowdkeeper --demo audit
type                subject               detail                                        fix
------------------  --------------------  --------------------------------------------  ------------
inactive            frank                 last login 140d ago                           deactivate
inactive            heidi                 last login 220d ago                           deactivate
disabled-in-groups  ivan                  disabled but in: bitbucket-users, jira-users  strip-groups
disabled-in-groups  mallory               disabled but in: finance, jira-admins         strip-groups
inactive            olivia                last login never                              deactivate
no-groups           olivia                active user in no groups                      review
inactive            rupert                last login 95d ago                            deactivate
disabled-in-groups  trent                 disabled but in: contractors                  strip-groups
no-groups           victor                active user in no groups                      review
inactive            svc-backup            last login 365d ago                           deactivate
no-groups           svc-backup            active user in no groups                      review
empty-group         legacy-sox-approvers  group has no members                          review
```

```text
$ crowdkeeper --demo fix
action             user        group
-----------------  ----------  ---------------
deactivate-user    frank
deactivate-user    heidi
remove-from-group  ivan        bitbucket-users
remove-from-group  ivan        jira-users
remove-from-group  mallory     finance
remove-from-group  mallory     jira-admins
deactivate-user    olivia
deactivate-user    rupert
remove-from-group  trent       contractors
deactivate-user    svc-backup

Dry run: 10 change(s) planned, nothing written. Use --apply to execute.
```

```text
$ crowdkeeper --demo jml examples/jml.csv
action             user     group
-----------------  -------  ----------------
create-user        newhire
add-to-group       newhire  jira-users
add-to-group       newhire  confluence-users
remove-from-group  bob      bitbucket-users
add-to-group       bob      confluence-users
remove-from-group  frank    finance
remove-from-group  frank    jira-users
deactivate-user    frank

Dry run: 8 change(s) planned, nothing written. Use --apply to execute.
```

```text
$ crowdkeeper --demo groups export -f a.json
$ # (a.json edited: zoe added to jira-admins, carol removed from finance, saved as b.json)
$ crowdkeeper groups diff a.json b.json
change   group        user
-------  -----------  -----
revoked  finance      carol
granted  jira-admins  zoe
```

`crowdkeeper --demo report` output:

```markdown
# Crowd Access Review

Generated: 2026-10-01 00:00 UTC  
Inactivity threshold: 90 days

## Summary

| Metric | Count |
|---|---|
| Users | 25 |
| Active users | 21 |
| Groups | 8 |
| Inactive users (>= 90d) | 5 |
| Active users with no groups | 3 |
| Disabled users still in groups | 3 |
| Empty groups | 1 |

## Findings

- **inactive** `frank`: last login 140d ago (recommended: deactivate)
- **inactive** `heidi`: last login 220d ago (recommended: deactivate)
- **disabled-in-groups** `ivan`: disabled but in: bitbucket-users, jira-users (recommended: strip-groups)
- **disabled-in-groups** `mallory`: disabled but in: finance, jira-admins (recommended: strip-groups)
- **inactive** `olivia`: last login never (recommended: deactivate)
- **no-groups** `olivia`: active user in no groups (recommended: review)
- **inactive** `rupert`: last login 95d ago (recommended: deactivate)
- **disabled-in-groups** `trent`: disabled but in: contractors (recommended: strip-groups)
- **no-groups** `victor`: active user in no groups (recommended: review)
- **inactive** `svc-backup`: last login 365d ago (recommended: deactivate)
- **no-groups** `svc-backup`: active user in no groups (recommended: review)
- **empty-group** `legacy-sox-approvers`: group has no members (recommended: review)

## Group sizes

| Group | Members |
|---|---|
| bitbucket-users | 5 |
| confluence-users | 9 |
| contractors | 3 |
| finance | 4 |
| hr | 2 |
| jira-admins | 3 |
| jira-users | 13 |
| legacy-sox-approvers | 0 |

_Produced by crowdkeeper. Remediate with `crowdkeeper fix` (dry-run by default)._
```

## Why no Crowd client library?

The Crowd client (`crowdkeeper/client.py`) is written directly on `requests` against
`/rest/usermanagement/1`, because there is no maintained Python Crowd client worth depending on.

## Development

```bash
pip install -e ".[test]"
pytest
```

## License

MIT
