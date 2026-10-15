# crowdkeeper roadmap

Plan for crowdkeeper by phase. Each phase ships something you can run from the command line. crowdkeeper stays CLI-only: no GUI, no web dashboard, no hosted service. Later phases do not block earlier ones. Versions are direction, not date promises.

## Current status

| Item | Details |
| --- | --- |
| **Latest release** | `v0.2.1` (2026-10-15): up-front JML validation and non-interactive `--apply` refusal; see [CHANGELOG.md](CHANGELOG.md). It did not include the Phase 1 items below. |
| **Next** | `v0.2.2` patch, then Phase 1: Harden (not started) |
| **Next target** | `v0.2.2` (patch), then `v0.3.0` (Phase 1) |

## Phase map

| Phase | Name | Version | Outcome | Status |
| --- | --- | --- | --- | --- |
| **0** | Foundation | `v0.1.0` | Six commands, demo mode, live Crowd client, safe apply, audit log, tests, CI | Done |
| **1** | Harden | `v0.3.0` | Retries, faster live scans, clear exit codes | Planned |
| **2** | Report | `v0.4.0` | Severity, exit-on-findings for CI, baselines | Planned |
| **3** | Policy | `v0.5.0` | Config file, exemptions, rollback from the audit log | Planned |
| **4** | Stable | `v1.0.0` | Stable CLI, flag names, JSON and audit log schema, exit codes | Planned |

## Phase 0: Foundation (v0.1.0)

**Goal:** Clone it and run every command in demo mode in about a minute.

- [x] `audit`: inactive users, active users with no groups, disabled users still in groups, empty groups, as table, JSON or CSV
- [x] `groups export` and `groups diff` to track access drift between two exports
- [x] `jml FILE.csv`: joiners, movers and leavers from a CSV, with input validation
- [x] `fix`: apply the audit's recommended cleanups
- [x] `report`: one-page Markdown summary for auditors, with Markdown escaping
- [x] `--demo` with a built-in directory of 25 users and 8 groups, never writes
- [x] Live Crowd client on `requests` against `/rest/usermanagement/1` with paged searches (v0.1.0 warned on `http://`; since v0.2.0 `https://` is required unless `--insecure`, and URLs with embedded credentials are always refused)
- [x] `jml` and `fix` dry run by default, `--apply` needs a typed `yes` or `-y`, and without `-y` a non-terminal stdin (piped, redirected, cron) is refused, so nothing changes
- [x] JSON lines audit log with `intent`, `applied` and `failed` entries, per-run `run_id`, secrets never logged
- [x] Partial failures and Ctrl-C stop the run, log what happened and exit `1`
- [x] CSV formula injection escaped
- [x] CI on Python 3.10 to 3.13 with pinned actions and least-privilege token

**Done when:** every command runs in demo mode as documented and CI is green. Landed in commits `dc93a4e` to `5f917b1`, with CI added in `c64fcd8` and after. Not tagged or released.

## Patch: v0.2.2

**Goal:** No Python tracebacks outside apply.

- [ ] Catch `KeyboardInterrupt` (and unexpected exceptions) outside apply and exit `130` with no traceback

## Phase 1: Harden (v0.3.0)

**Goal:** Live mode you can point at a large production directory without surprises.

- [ ] Retries for 429, 5xx and connection errors with `Retry-After` and capped backoff
- [ ] Fewer round trips for last-login lookups so big directories scan quickly
- [ ] Documented exit codes for usage, Crowd and partial apply errors
- [ ] Tests against recorded Crowd API responses
- [x] First tag, GitHub release and `CHANGELOG.md` (v0.2.0)

**Done when:** an audit of a directory with thousands of users finishes cleanly under throttling and `v0.3.0` is tagged.

## Phase 2: Report (v0.4.0)

**Goal:** Feed crowdkeeper results into scheduled jobs and other tools, not just terminals.

- [ ] Severity per finding and `--fail-on SEVERITY` exit code for CI gates
- [ ] Documented JSON schema for `audit` and `groups export`
- [ ] `--baseline FILE` to report only new findings since a saved run
- [ ] `report` includes group drift when given two exports

**Done when:** a scheduled job can run `crowdkeeper audit` and fail only on new findings.

## Phase 3: Policy (v0.5.0)

**Goal:** Let admins encode their own rules without forking it.

- [ ] Config file for inactivity thresholds, protected groups and service accounts
- [ ] Exemptions with a required reason and optional expiry date
- [ ] `undo` that plans the reverse of a run from its audit log, dry run by default

**Done when:** exemptions and thresholds live in config and every change stays dry run by default.

## Phase 4: Stable (v1.0.0)

**Goal:** A contract other people can build on.

- [ ] Freeze command names, flags, JSON and audit log schema, and exit codes
- [ ] Deprecation policy for anything that changes after `v1.0.0`
- [ ] Published to PyPI with signed releases
- [ ] Docs for the Crowd application permissions each command needs

**Done when:** the contract is documented, tested and released to PyPI.

## Out of scope

- A GUI, web dashboard or hosted service. crowdkeeper is CLI-only.
- Replacing Crowd or acting as an identity provider.
- Continuous monitoring or alerting. It is a point-in-time review and change tool.
- Silent changes. Every change stays a dry run unless `--apply` is given and confirmed.
