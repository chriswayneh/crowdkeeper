# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | Yes |
| < 0.2 | No (please upgrade) |

Security fixes go into the latest 0.2.x release only.

## Reporting a vulnerability

Please do **not** open a public issue, discussion or pull request for a security problem.

Report it privately with GitHub private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**. Include the crowdkeeper version, the
command you ran, what happened, and steps to reproduce. Remove real passwords, hostnames and user
data from anything you send.

You should get an acknowledgement within 5 business days. We will agree on a fix and disclosure
timeline with you and credit you in the advisory unless you prefer otherwise.

## Scope

In scope:

- The `crowdkeeper` package and CLI in this repository: `audit`, `groups`, `jml`, `fix`, `report`.
- Handling of `CROWD_URL`, `CROWD_APP` and `CROWD_APP_PASSWORD`, including any leak of the
  application password into output, error text or the audit log.
- Unsafe writes: changes made without `--apply` and confirmation, writes in `--demo` mode, or
  changes that are applied but not recorded in the audit log.
- CSV/Markdown injection in exported output, and unsafe parsing of JML CSVs or group snapshots.

Out of scope:

- Vulnerabilities in Atlassian Crowd itself (report those to Atlassian) or in third-party
  dependencies (report upstream; we will bump our minimum version).
- Risks you accept by passing `--insecure` (plain http sends the app password unencrypted).
- Attacks that need prior control of the machine, the environment variables or the audit log file.
