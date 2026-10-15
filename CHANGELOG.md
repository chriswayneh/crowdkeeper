# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-14

### Changed
- **Breaking: new audit-log format.** Each applied change now writes an `intent` line before the
  Crowd call and an `applied` line after it; on error a `failed` line is written. Every line carries
  `seq` (restarts at 1 each run) and `run_id` (random per run), so `(run_id, seq)` identifies a change.
  The change's own fields sit under a nested `detail` object. `failed` lines add `stage`
  (`intent_log`, `change`, `applied_log`), `change_applied` (`true`, `false`, or `null` meaning
  unknown, e.g. Ctrl-C during the Crowd call), `error` and `applied_before_failure`.
  **Readers of the old one-line-per-change log must be updated.**
- `auditlog.record` rejects reserved top-level field names (`ts`; `event`, `action` and `detail` are positional parameters and cannot be passed as extra fields).

### Fixed
- `fix` and `jml` log every change already applied plus the failure when they stop partway, and
  exit with status 1 (including on Ctrl-C, without a traceback).
- If the failure entry cannot be written, the original error is still printed to stderr.
- Secrets (app password, URL credentials) are masked in logged error text.

## [0.1.0]

- Initial release: `audit`, `groups`, `jml`, `fix`, `report` commands with `--demo` mode.
