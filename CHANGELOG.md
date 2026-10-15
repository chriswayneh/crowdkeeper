# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.2.3] - Unreleased

### Fixed
- `jml` leavers are now deactivated before their group memberships are removed, so a failed removal
  can no longer leave the account active (the plan order changed: `deactivate-user` comes first).
- The Crowd client no longer follows redirects and treats every non-2xx answer (including a 3xx to a
  login page) as an error, so such a change is logged as failed instead of applied.
- `--apply` re-reads the directory and re-plans right before applying; if the plan differs from the
  confirmed preview, it exits 1 and changes nothing. `fix` now recomputes the audit for that check.
- Deactivation sends only the identity fields and `active: false`, not the whole fetched user, and
  refuses to write if Crowd's answer isn't the requested user.
- Malformed Crowd responses (missing or non-list `users`/`groups`/`attributes`, entries without a
  name) raise an error instead of reading as empty results (a falsely clean audit or zero removals).
- `jml` CSV headers are matched after stripping spaces, so `groups ` is no longer silently ignored,
  and unknown columns are rejected with exit 2.
- `report` reads the directory once, so all sections describe the same state.

### Documentation
- README states that membership is direct-only (nested groups aren't read or changed) and documents
  the re-check before apply.

## [0.2.2] - 2026-10-15

### Changed
- Visible output change: in the plain table, CSV, Markdown report and CLI error messages, invisible
  characters (tab, newline, ESC, bidi, zero-width and similar) now print as Python-style escapes
  such as `\t`, `\n`, `\u001b` and `\u202e`, and a literal backslash prints doubled (`\\`).
  Use `-o json` for exact names. Bad JML input now always exits 2.

### Fixed
- `jml` parses the CSV strictly. Duplicate or blank column headers (for example two `groups`
  columns, which could plan removal of all of a user's groups) and broken quoting (an unclosed
  quote, or text after a closing quote, which could still plan a removal or deactivation) are now
  rejected with a line-numbered error, exit 2 (the usage-error code), and nothing is planned or
  changed.
- The Markdown `report` escapes `[ ] ( ) ! *` and HTML (`&`, `<`, `>`) in user and group names,
  so a name can't render as a link, image, emphasis or HTML. Finding subjects shown in code
  spans are left unescaped apart from backticks and newlines, since Markdown and HTML aren't
  interpreted there.
- `jml` reads the CSV as UTF-8 with an optional BOM. These also stop the run with a line-numbered
  error and exit 2, before anything is planned: an empty file (no header), a missing required
  header (`action`, `username`; was exit 1), a row with more or fewer values than the header
  (short rows were previously accepted), bytes that aren't UTF-8, and any control, format or
  separator character in a field (NUL, tab, ESC, C1, U+202E, U+200B, U+2028, line breaks inside
  quotes).
- The Markdown `report` also escapes `_` and `~` and breaks autolinks (`://`, `www.`, `@`), and in
  both escaped text and code spans it shows control, bidi, zero-width and line/paragraph separator
  characters as visible escapes (`\u001b`), so report output can't inject terminal escapes (ESC, OSC 8)
  or reorder text.
- Row validation errors in `jml` (unknown action or group, missing username, a mover or leaver who
  doesn't exist) now exit 2 like other input errors (was 1), and their line numbers are the real
  file lines, so blank lines no longer shift them. Through the Python API they raise
  `core.JmlInputError`, a `ValueError` subclass; `core.jml()` takes an optional `lines` list.
- The plain table and CSV outputs and CLI error messages show control, bidi, zero-width and
  separator characters as visible escapes (shared `core.term_safe` helper). JSON is unchanged: it
  already writes them as `\uXXXX` escapes and keeps the exact value.
- `term_safe` writes those characters as Python-style escapes (`\u001b`, `\t`, `\n`) and doubles a
  literal backslash, so a name containing the text `U+001B` or `\u001b` can't be mistaken for a
  real control character.
- The Markdown `report` escapes every `.` and puts each run of `@` in a code span, so bare domains
  (`evil.com`, `xn--...`), `//host` paths and e-mail or `mailto:` addresses no longer autolink in
  cmark-gfm (GitHub) or markdown-it linkify.

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
