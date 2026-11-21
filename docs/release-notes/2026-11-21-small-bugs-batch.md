# small-bugs-batch

PR: #1223

## What changed
Parent makeups (#1041) now say why a flagged class can't be made up (late notice, already requested, marked present, cancelled), and why the picker is empty. Coaches can deselect every student in the bulk skill update (#1042). The BFF proxy stops forwarding stale `content-encoding`/`content-length` (#1067). A class copy retry now names the copy it already made and offers to open it, where it used to be a dead-end 409. Admin "Charge card now" answers 503, not 500, when billing settings can't be read, and on a decline or a charge that was never attempted it keeps the dialog open with the reason (an unreachable Stripe reads "Couldn't reach Stripe, try again", not a decline) instead of closing silently. A pending ACH or 3DS charge still closes, so a second click can't start a second charge.

## Deploy notes
None. No migration, env var or manual step. `GET /parent/makeups/candidates` gains optional fields (`makeups_enabled`, `requires_notice`, `ineligible`); older cached PWA clients ignore them.

## Risk / rollback
Charge path: only a settings-read failure changes, from an unhandled 500 to a 503 (`Billing.SettingsUnavailable`); the dunning worker still parks it as a technical failure, and nothing reaches Stripe. Proxy: responses lose `content-length`, so the runtime streams them chunked; `apiFetch` now detects an empty body by reading it rather than by that header. Roll back by reverting the PR.
