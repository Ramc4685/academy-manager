# Ops alerting: boot warning for a missing OPS_ALERT_EMAIL, and Sentry alert rules as code (D10)

PR: #941

## What changed

- **Boot warning.** When `OPS_ALERT_EMAIL` is empty, the backend logs one WARNING `ops_alert_email_missing` (`event=ops_alert_email_missing`, `env=<settings.env>`) per process at startup. The daily ops digest still skips when the secret is unset, exactly as before. The warning just makes the gap visible (`backend/v2/shared/observability/ops_alerts.py`, one lifespan call in `backend/v2/main.py`).
- **Sentry alert rules as code.** `backend/scripts/sentry_alert_rules.py` declares three `[managed]` issue-alert rules for `courtmastr-fastapi` and `courtmastr-frontend`: new issue in production, issue affecting 5+ users in 1h, and an error spike on `/billing` transactions. It reconciles them idempotently through the Sentry rules API (create missing, update changed, no-op identical, never delete). Dry run is the default and `--apply` writes. The token comes only from `SENTRY_AUTH_TOKEN` and is never printed.
- **Runbook.** `docs/runbooks/sentry-alerts.md` covers both.

## Deploy notes

- No migration.
- Owner-only step: if prod logs `ops_alert_email_missing` after deploy, set the secret with `fly secrets set OPS_ALERT_EMAIL=<owner inbox> -a <backend-app>`.
- Owner-only step: to install the alert rules, export a `SENTRY_AUTH_TOKEN` with project read/write (alerts) scope. Run `python -m backend.scripts.sentry_alert_rules` to review the dry run, then run it again with `--apply`. Nothing changes in Sentry until someone runs `--apply`.

## Risk / rollback

- Very low. The boot change is one log line and does not alter the digest or startup behaviour. The script runs only by hand and never deletes Sentry rules.
- Rollback: revert the PR. Rules already applied in Sentry stay until someone deletes them in the Sentry UI.
