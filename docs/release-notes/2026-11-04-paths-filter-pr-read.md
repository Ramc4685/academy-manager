# paths-filter-pr-read

PR: #1129

## What changed
The Production workflow's Detect Changes job now has `pull-requests: read`. Since about 22:00Z on 2026-11-04 its paths-filter step failed on every PR with "Resource not accessible by integration", which skipped every required job and turned CI Gate red. A rerun of #1126's job on the same commit that had passed at 21:20Z failed the same way, so the cause was outside the code.

## Deploy notes
None. Open PRs need main merged in (or a re-run after this lands) to pick up the fix.

## Risk / rollback
A read-only scope on one job, with no write access added. Revert this PR to remove it; Detect Changes would fail on PRs again.
