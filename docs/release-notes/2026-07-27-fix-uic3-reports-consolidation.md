# fix-uic3-reports-consolidation

PR: #PENDING

## What changed
Session economics and Dues follow-up are now sub-reports under Reports
(`/admin/reports/session-economics`, `/admin/reports/dues`) instead of
separate MONEY nav items, and both appear as cards on the Reports hub. The
old `/admin/session-economics` and `/admin/dues` URLs redirect, so existing
bookmarks and the dashboard's overdue-dues link keep working. Page content is
unchanged — the tuition-discounts panel and the dues reminder action moved
across intact.

## Deploy notes
None. No migrations, no env vars. Backend report/dues APIs are untouched.

## Risk / rollback
Low: pure route relocation plus additive redirect stubs. If a link is missed,
the old URL still redirects rather than 404s. Rollback by reverting the PR,
which restores the original route paths.
