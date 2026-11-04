# phase1-s6-powered-by-referral

PR: #TBD

## What changed
Distribution groundwork (AI strategy Phase 1, slice 6). Every family email rendered through the shared `shell()` gets a "Powered by CourtMastr" link under the academy's "Sent by" line; the golden brand-parity fixtures were updated by that one line only. The public tenant page's existing "Bookings and payments by CourtMastr" credit now links to the platform site. Each tenant gets a `referral_code` (derived from the slug on first read, then kept, so a later slug change does not break links already shared); the platform tenant detail response carries `referral_url` (`<frontend_url>/?ref=<code>`) and the platform tenant detail page shows it as one read-only line. The backfill is a targeted `$set` on the missing field, not a whole-document save, so a concurrent status or fee write cannot be undone by a read. Nothing consumes `?ref` yet. `referral_url` is null in the tenant list and create responses (the code is lazy) and in the detail response when `V2_FRONTEND_URL` is unset.

## Deploy notes
No migration: `referral_code` is optional and backfilled on first read of each tenant through `GET /api/v2/platform/tenants/{id}/status` or any lifecycle mutation. No new env var; `referral_url` uses the existing `V2_FRONTEND_URL`.

## Risk / rollback
Low. The email change is a footer line on every family email; the referral code is informational and unused. Rollback is a revert of the merge commit; backfilled `referral_code` values can stay in `academies` docs harmlessly.
