# admin-dashboard-resilience-and-connect-onboarding-errors

PR: #287

## What changed
Admin dashboard `/dashboard/attention` no longer 500s entirely when one
attention source fails (e.g. `waiver_report` returning `None`) — each of the
6 sources is now isolated and falls back to a safe default. Stripe Connect
onboarding errors (`create_connected_account`, `create_account_onboarding_link`)
now surface as a structured `ConnectOnboardingFailed` (502) instead of a raw
500. Also quiets two noisy service-worker console errors (Cloudflare Insights
beacon, Firebase-auth network-only handler) and cleans up `.gitignore` for
scratch/session artifacts.

## Deploy notes
None. No migration, no env vars, no schema change. Backend + frontend, both
covered by the standard CI deploy pipeline.

## Risk / rollback
Low risk — purely additive error handling/isolation, no behavior change on
the happy path. If a regression appears, revert the merge commit; no data
migration to unwind.
