# crowdkeeper roadmap

Plan for crowdkeeper by phase. Each phase ships something you can run from the command line. crowdkeeper stays CLI-only: no GUI, no web dashboard, no hosted service. Later phases do not block earlier ones. Versions are direction, not date promises.

## Current status

| Item | Details |
| --- | --- |
| **Latest release** | `v0.2.4` (2026-10-22): Ctrl-C outside `--apply` exits `130`, malformed `groups diff` files are named, mypy-clean tests, CI and Dependabot hardening; see [CHANGELOG.md](CHANGELOG.md). Other Phase 1 items below are still open. |
| **Next** | Phase 1: Harden |
| **Next target** | `v0.3.0` (Phase 1) |

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

## Patch: v0.2.3 (shipped 2026-10-15)

**Goal:** Fix verified Codex review findings in live-mode safety.

- [x] Leavers deactivated before group removal
- [x] Client: no redirects, only 2xx is success; malformed responses are errors
- [x] Re-plan before apply and abort on drift; minimal deactivate body
- [x] JML header names stripped, unknown columns rejected; `report` uses one snapshot
- [x] Crowd decision fields validated (`active`, names, timestamps); non-JSON 2xx is an error
- [x] README: membership is direct-only

## Patch: v0.2.2 (shipped 2026-10-15)

**Goal:** Strict input parsing and safe report and terminal rendering.

- [x] Strict JML CSV parsing: duplicate or blank headers and broken quoting exit `2` with a line number, nothing changed
- [x] Strict JML CSV: UTF-8 (optional BOM) required, an empty file or a missing required header rejected
- [x] Strict JML CSV: row length must match the header (short and long rows exit `2`)
- [x] Strict JML CSV: any control character, bidi or zero-width character in a field exits `2`
- [x] JML row errors (unknown action or group, missing username, unknown mover/leaver) exit `2` with real file line numbers
- [x] `report` escapes Markdown link/emphasis characters, HTML and autolinks (URLs, `www.`, fuzzy domains, e-mail) in names, checked with cmark-gfm and markdown-it linkify
- [x] Terminal-safe output: one `term_safe` helper escapes control, bidi and zero-width characters in the table, CSV, report and error messages

## Patch: v0.2.4 (shipped 2026-10-22)

**Goal:** Close QE findings on the post-v0.2.3 main and harden CI.

- [x] Ctrl-C outside `--apply` exits `130` with a one-line message and no traceback
- [x] A malformed `groups diff` file is named in the error message (exit `1`)
- [x] Tests pass mypy with no errors
- [x] Dependabot for pip and GitHub Actions, `actions/checkout` 7.0.1, `actions/setup-python` 7.0.0, and `persist-credentials: false` in CI

## Phase 1: Harden (v0.3.0)

**Goal:** Live mode you can point at a large production directory without surprises.

- [x] Catch `KeyboardInterrupt` outside apply and exit `130` with no traceback (moved from v0.2.2, shipped in v0.2.4)
- [ ] Catch unexpected exceptions outside apply with a short message instead of a traceback
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
