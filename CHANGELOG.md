# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-10-15

### Fixed
- `jml` now checks every row up front, before any change, including when `core.jml` is called
  directly with `Executor(apply=True)`: unknown action, empty username, and movers or leavers that
  don't exist (users created by earlier joiner rows count). Previously a valid row before a bad one
  could already have been applied through the API. All bad lines are reported together.
- The `--apply` confirmation prompt refuses when stdin is not a terminal and `-y` isn't passed, so
  piped input such as `echo yes |` can't confirm a change, and exits 2 (the usage-error code) so cron and CI
  see a failure. Previously only end-of-input counted as no. Declining at an interactive prompt
  still exits 0.

## [0.2.0] - 2026-10-15

### Changed
- **Breaking: new audit-log format.** Each applied change now writes an `intent` line before the
  Crowd call and an `applied` line after it; on error a `failed` line is written. Every line carries
  `seq` (restarts at 1 each run) and `run_id` (random per run), so `(run_id, seq)` identifies a change.
  The change's own fields sit under a nested `detail` object. `failed` lines add `stage`
  (`intent_log`, `change`, `applied_log`), `change_applied` (`true`, `false`, or `null` meaning
  unknown: Ctrl-C, timeout, lost response or 5xx during the Crowd call; `false` only for a 4xx
  rejection or a failed `intent` write), `error` and `applied_before_failure`.
  **Readers of the old one-line-per-change log must be updated.**
- `auditlog.record` rejects reserved top-level field names (`ts`; `event`, `action` and `detail` are positional parameters and cannot be passed as extra fields).
- **Breaking:** `CROWD_URL` must be `https://` and must not contain credentials; the client refuses
  to start otherwise (was a warning). Plain `http://`, localhost included, needs the new global
  `--insecure` flag, which logs a warning.
- **Breaking:** `jml` movers: a blank `groups` cell (empty, spaces, or only `;`) now leaves
  memberships alone. Removing every group requires the explicit marker `-` or `none`; mixing it
  with group names is rejected with the line number. A single-quoted token (`'none'`, `'-'`) is a
  literal group name, so real groups with those names can still be listed alongside others.
- Requires `requests>=2.32.4` (CVE-2024-35195 was fixed in 2.32.0, CVE-2024-47081 in 2.32.4).
- Error text masks an app password of 8+ characters anywhere, and a shorter one only where no letter
  or digit touches it, so short passwords no longer mangle unrelated words.
- **Breaking:** users with no recorded login are now `activity-unknown` (review) instead of
  `inactive` (deactivate), and are only flagged once the account is older than `--days`.
- `--days` must be a positive whole number (`audit`, `fix`, `report`, and the core API).
- `jml` checks the whole CSV first (required `action`/`username` columns, extra values, unknown
  groups, with line numbers) and makes no change if anything is wrong. (Through the API this held
  only for those checks until 0.2.1, which also validates actions, usernames and user existence.)
- Prompts and status messages go to stderr; stdout carries only the selected output format.

### Fixed
- `fix --apply` could deactivate brand-new accounts that had not logged in yet.
- `jml`: several rows for one user are applied in order against the updated state (mover and back,
  repeated joiner no longer creates twice).
- `jml`: a missing `groups` column, truncated row or blank `groups` cell no longer removes every
  mover membership; only an explicit `-` or `none` does.
- A Ctrl-C while writing a change's `applied` line now logs a `failed` entry with
  `stage: applied_log` and `change_applied: true` before the interrupt propagates.

### Added
- `SECURITY.md` (supported versions, private reporting, scope) and a `[tool.ruff]` config.
- `--apply` executes exactly the confirmed plan instead of re-planning after the prompt.
- Membership reads now paginate past Crowd's 1,000-result page.
- CLI error messages mask the app password and URL credentials.
- `groups diff` rejects malformed snapshots with a clear error instead of a traceback.
- `fix` and `jml` log every change already applied plus the failure when they stop partway, and
  exit with status 1 (including on Ctrl-C, without a traceback).
- If the failure entry cannot be written, the original error is still printed to stderr.
- Secrets (app password, URL credentials) are masked in logged error text.

## [0.1.0]

- Initial release: `audit`, `groups`, `jml`, `fix`, `report` commands with `--demo` mode.
