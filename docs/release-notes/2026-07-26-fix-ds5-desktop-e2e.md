# fix-ds5-desktop-e2e

PR: #364

## What changed
CI now exercises the desktop admin layout: a new `chromium-desktop` (1280x800)
Playwright project runs the admin-shell, admin-students, and admin-registrations
specs against the real `lg:` sidebar, not just the mobile drawer. A shared
`gotoAdminNav`/`openAdminNav` helper keeps nav assertions correct on both the
sidebar and drawer surfaces.

## Deploy notes
None — test-only change, no product code, no migrations.

## Risk / rollback
Risk: adds a few minutes to CI wall-time (bounded to 3 specs via `testMatch`).
Rollback: revert the PR — deletes the project block and helper, touches no
product code.
