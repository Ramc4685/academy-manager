# real-auth-admin-session-e2e

PR: #598

## What changed
Adds `frontend/e2e/specs/local-auth-sessions.spec.ts`, a real-auth Playwright
spec that signs in as the seeded BLno admin and drives the real backend against
local SaaS staging. The #467 (cancel a session does nothing) and #503 ("Add to
roster" crashes the page) fixes from #589 already had stubbed admin-shell specs
and backend pytest, but nothing exercised them end to end through a real login.

The #503 test opens "Add to roster" on the seeded session detail page and
asserts the page survives instead of unwinding to the root error boundary, then
that the dialog's Cancel closes it. The #467 test creates its own session
through the create dialog, cancels it, asserts the row disappears, and then
reloads so the final assertion is served by a fresh backend listing rather than
in-memory table state.

Cancelling cannot be undone, so the spec cancels a session it created rather
than a seeded one — the BLno seed is left untouched and the spec is re-runnable.
Row counting keys off the existing `session-row-*` testid: while the sessions
query is in flight the page renders a skeleton with no `tbody`, so a structural
`tbody tr` count silently reads 0. No production code changed.

`frontend/playwright.local-auth.config.ts` gains the new spec in `testMatch` and
splits its projects: the sessions table scrolls horizontally and puts the row
actions off-screen at Pixel 7 width, so the new spec runs in a new
`local-auth-chromium-desktop` project while the two existing specs stay on
mobile.

The spec was verified to fail against pre-fix code. Reverting the
`{"status": {"$ne": "cancelled"}}` predicate in `backend/v2/composition/admin.py`
alone is not sufficient — #589 also added an independent cancelled guard to
`synthesize_recurring_session_docs`, and sessions created through the UI are
recurring templates, so that path is defended twice. With both halves reverted
the cancelled row is still present after reload and the test fails on the
`toHaveCount(0)` assertion; restored, it passes.

## Deploy notes
None. Test-only change with no production code, no migration, and no new
environment configuration. The spec is gated behind `LOCAL_AUTH_E2E=1` and skips
by default, and it runs only under `playwright.local-auth.config.ts`, which is
not part of the CI or pre-push e2e gate — it is a local staging tool requiring
`scripts/dev/saas_staging.sh up`, `blno-seed`, and `local-auth-env`.

## Risk / rollback
Effectively zero production risk: nothing ships to the app. The change is
additive to a manually invoked local suite. Rollback is deleting the spec file
and reverting the two-project split in `playwright.local-auth.config.ts`.

Two pre-existing local-staging problems were found while writing this and are
deliberately not addressed here: `GET /api/v2/admin/users` (unfiltered) returns
500 because one seeded user with a `.test` email fails pydantic `EmailStr` and
`list_users` fails wholesale rather than skipping the row (those users come from
`scripts/dev/scale_blno_staging.py`, not `blno-seed`; `?role=coach` is
unaffected), and `local-auth-inventory.spec.ts` measures 78 failed / 8 passed on
a baseline with this change removed.
