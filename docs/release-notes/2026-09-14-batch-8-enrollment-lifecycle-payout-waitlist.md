# Batch 8: enrollment lifecycle, payout period audit, waitlist confirmation window

PR: #0

## What changed

- Fixes #820 — Admin "drop at end of period" now schedules the drop instead of
  performing it immediately. The withdraw route gained an optional
  `defer_to_period_end`; when set it stamps `pending_cancellation_at` (already
  rendered as "ends \<date\>" on the roster/profile/coach surfaces) and enqueues
  an admin-owned `admin_drop_at_period_end` scheduled action for the
  academy-local month end, leaving the row live and seated until the hourly
  worker replays the withdraw with the original outcome and actor. A new
  `cancel-scheduled-drop` route lets an admin call off a drop that hasn't
  fired yet.
- Fixes #821 — Re-verified the payout-period audit-trail spec: the
  `payout_periods` draft→approved→paid state machine, owner-gated
  approve/pay/reopen routes, the `PayoutPeriodLock` that freezes coach
  attendance during a locked period, migration 0103's collections, and the
  payroll page's status chip + audit trail were already shipped under #787 /
  PR #799. No new migration, collection, or route was needed for this issue.
  Also fixed a related gap: an owner can now correct attendance inside a
  locked payout period with an audited reason.
- Fixes #828 (Part 1) — A freed waitlist seat now holds for a real 3-day
  confirmation window instead of being seated instantly. `PromoteFromWaitlist`
  holds the seat (via `SeatBroker` where wired) and marks the waitlist entry
  `offered` with `offer_expires_at = now + 3 days`, emailing the family to
  confirm by that date. A new parent route,
  `POST /api/v2/parent/waitlist/{waitlist_id}/confirm`, runs
  `ConfirmWaitlistOffer` (ownership-checked, deadline-checked, idempotent — a
  second confirm returns the existing enrollment rather than creating a
  duplicate). A new hourly job, `sweep_expired_waitlist_offers`, releases
  unanswered offers, marks them `expired`, notifies the family, and offers the
  seat to the next person in line. An already-active row and a paused row
  coming back through `ResumeEnrollment` both skip the window, since no seat
  is being handed to a new family in either case. Part 2 of #828 (the "your
  last class is \<date\>" reminder in `process_scheduled_cancellation_actions`,
  plus pause-ending / first-class / level-up notices) is **not** in this PR —
  tracked as follow-up.
- Fixes #827 — four independent fixes bundled together: forwarding the
  retired-people bookmarks before the layout renders, offering "Re-enroll" on
  a departed roster row, offering "Enroll in a class" on a departed child's
  row in the parent portal, and letting a returning family pick the child
  they already have during onboarding.

## Deploy notes

- Migration 0183 widens migration 0133's `waitlist.status` enum to add
  `offered` / `expired` and types `offer_expires_at`. It runs automatically on
  boot like the rest of this repo's migrations; no manual step required.
- No other new migrations, collections, or manual environment/config changes.
- The new hourly jobs (`admin_drop_at_period_end` processing and
  `sweep_expired_waitlist_offers`) ride the existing scheduler loop — no new
  cron wiring needed.

## Risk / rollback

- Risk is scoped to enrollment withdraw/drop timing and waitlist promotion
  timing; no payment amounts or invoice shapes change. The payout-period
  audit trail (#821) was already live on main, so that half of this PR is
  read-only verification plus a small attendance-correction fix.
- Rollback: revert this PR. The waitlist enum widening (migration 0183) is
  additive (new enum values only) and safe to leave in place even if the PR
  is reverted; no backfill or down-migration is required.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
