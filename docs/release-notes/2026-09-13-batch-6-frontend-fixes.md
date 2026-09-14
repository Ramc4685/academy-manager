# Batch 6: scope coach lookup and identify Sentry users

## What changed
- Fixes #521 — Admin session-detail page fetched the entire tenant user directory (all roles) just to label coach names in the replacement-coach table. Switched to `listAdminUsers("coach")` / `queryKeys.admin.users("coach")` so it fetches only coach-role users, matching the API's existing role filter support.
- Fixes #750 — Frontend Sentry now identifies the signed-in user (`Sentry.setUser`), so "users affected" on Sentry issues stops reading 0.

## Deploy notes
No migrations. No manual steps. Pure frontend query-scoping and Sentry client config changes.

## Risk / rollback
Low risk: #521 narrows an existing query's filter parameter (already supported server-side) rather than changing behavior; #750 only adds user identification to error reports, no user-facing behavior change. Rollback is reverting this PR.

PR: #800
