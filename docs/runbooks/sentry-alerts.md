# Sentry alerts (roadmap D10)

Two small guards against failures nobody hears about.

## 1. `ops_alert_email_missing` boot warning

The daily ops digest (`send_ops_digest`, 07:00 scheduler time) emails the
owner about quarantined Stripe webhooks, dead-letter events, dunning
terminals and stale jobs. With `OPS_ALERT_EMAIL` unset it skips every cycle
with an INFO line, so a deployment without the secret looks healthy.

At startup the backend now logs one WARNING per process:

```
ops_alert_email_missing: OPS_ALERT_EMAIL is not configured; the daily ops digest will be skipped (env=prod)
```

The log record carries `event=ops_alert_email_missing` and `env=<settings.env>`.
The digest itself behaves the same as before. To clear the warning, the
owner sets the secret (owner-only step, not done by code):

```bash
fly secrets set OPS_ALERT_EMAIL=<owner inbox> -a <backend-app>
```

## 2. Issue-alert rules as code

`backend/scripts/sentry_alert_rules.py` declares the issue-alert rules for the
`blno-badmintion` org and reconciles them against Sentry. It targets
`courtmastr-fastapi` (environment `prod`) and `courtmastr-frontend`
(environment `production`). Each project gets these rules:

| Rule | Trigger | Throttle |
| --- | --- | --- |
| `[managed] New issue in production` | first event of a new issue | 5 min |
| `[managed] Issue affecting 5+ users in 1h` | 5 or more unique users in 1 hour | 60 min |
| `[managed] Error spike on /billing routes` | 10 or more events in 1 hour where the `transaction` tag contains `/billing` | 30 min |

Every rule emails the issue owners and falls back to active members.

### How it reconciles

1. `GET /api/0/projects/{org}/{project}/rules/`
2. It matches each declared rule by **name**. The `[managed]` prefix marks
   rules this script owns.
3. It sends `POST` when a rule is missing and `PUT .../rules/{id}/` when a
   managed field differs (name, environment, actionMatch, filterMatch,
   frequency, conditions, filters or actions). When the fields match, it
   does nothing.

It never deletes anything. Rules it does not declare are listed as `SKIP ...
(unmanaged, left untouched)`. To retire a managed rule, remove it here and
delete it in the Sentry UI.

### Running it

The token comes from the environment only. Create an internal-integration or
user auth token with `project:read` and `project:write` (alerts:write)
scopes. The script never prints the token.

```bash
export SENTRY_AUTH_TOKEN=...          # do not paste into shell history on shared machines
backend/.venv/bin/python -m backend.scripts.sentry_alert_rules            # dry run (default): prints the plan and diff
backend/.venv/bin/python -m backend.scripts.sentry_alert_rules --apply    # writes creates/updates
```

A dry run still reads the current rules. It exits 0 and prints
`Dry run: N change(s) pending`. Exit codes: `0` ok, `1` Sentry API error
(for example HTTP 403 on a token without the scopes), `2` for a missing
`SENTRY_AUTH_TOKEN`. `SENTRY_URL` or `--base-url` override `https://sentry.io`.

To change a rule, edit `_rules_for()` and run the unit tests
(`backend/v2/tests/unit/test_sentry_alert_rules.py`). Run a dry run to review
the diff, then `--apply`. Keep the rule table above in sync, since a unit
test checks that this runbook names every declared rule.
