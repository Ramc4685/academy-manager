# small-bugs-batch

PR: TBD

## What changed
Parent makeups (#1041) now say why a flagged class can't be made up (late notice, already requested, marked present, cancelled), and why the picker is empty. Coaches can deselect every student in the bulk skill update (#1042). The BFF proxy stops forwarding stale `content-encoding`/`content-length` (#1067). A class copy retry now names the copy it already made and offers to open it, where it used to be a dead-end 409. Admin "Charge card now" answers 503, not 500, when billing settings can't be read, and tells the admin "Couldn't reach Stripe, try again" (or the real decline reason) in place of closing silently.

## Deploy notes
None. No migration, env var or manual step. `GET /parent/makeups/candidates` gains optional fields (`makeups_enabled`, `requires_notice`, `ineligible`); older cached PWA clients ignore them.

## Risk / rollback
Charge path: only a settings-read failure changes, from an unhandled 500 to a 503 (`Billing.SettingsUnavailable`); the dunning worker still parks it as a technical failure, and nothing reaches Stripe. Proxy: responses lose `content-length`, so the runtime streams them chunked. Roll back by reverting the PR.
