# Enrollment lifecycle notifications

PR: #767

## What changed

- Fixes #616 — Staff are alerted on new pause requests, the pause-review queue ages correctly, and review dates are clamped to valid ranges (items 3, 4, 5 of #616; items 1-2 were already on `main`).
- Fixes #743 — Admin-initiated Drop (`WithdrawEnrollment`, and "Stop all classes" which composes it) and Return from hold (`ReturnFromHold`) now email the affected family, mirroring the existing `hold_started` notice wiring. Added `enrollment_dropped`/`enrollment_returned` to the `HoldNotifier` port and `HoldNotificationAdapter` (keyed by `enrollment_id`, distinct from the `hold_seq`-keyed hold notices); sends are best-effort (try/except) after the write commits, so a notification failure never blocks the drop/return itself.
- Fixes #742 — The single-enrollment Drop dialog now opens on the academy's configured departure-policy default instead of a credit/refund choice keyed off the admin's role. Added `policyWithdrawalOutcome`/`initialWithdrawalOutcome` to `lib/admin/withdrawal.ts`; "Stop all classes" now delegates to the same mapping so the two drop paths cannot drift. The dialog reads the shared `queryKeys.admin.departurePolicy()` cache key (shared with Settings and the student page) and falls back to today's role default while the policy is loading or absent; it never pre-selects the owner-gated credit option for a plain admin.
- Fixes #691 — A session move that re-prices the current period could raise an autopay family's open invoice after the pre-charge notice had already been emailed, silently charging more than quoted. The use case's `notice_stale` result/audit event is now consumed to re-notify the family before the higher amount is charged.

## Deploy notes

No migrations. No new environment variables. Frontend and backend ship together (the Drop dialog and the notifier wiring are both touched); no manual steps required before or after deploy.

## Risk / rollback

- All four changes are additive/corrective to existing enrollment-lifecycle code paths (drop, return-from-hold, pause review, autopay re-pricing notices); no new schema or contract changes.
- Notification sends are best-effort and wrapped in try/except, so a mail-provider outage cannot block a drop or return-from-hold write.
- Rollback: revert this PR's merge commit. No data migration to reverse; any emails already sent are informational only.
