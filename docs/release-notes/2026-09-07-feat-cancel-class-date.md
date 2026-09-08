# feat-cancel-class-date

PR: #685

## What changed

Admins can call off a single class date (rain-out, sick coach, holiday) instead
of cancelling the whole session, and the money and payroll follow automatically.
Issue #671.

**Owner policy implemented here** (state it to the academy before deploying):
a cancelled date automatically credits every family who has already been priced
for the month — an invoiced family, and a family who paid their first month at
registration checkout — the date's share of what they were charged, through the
account credit ledger. A family whose month is not priced yet is not credited:
the generator simply leaves the date out of their first-month numerator. There
is no make-up entitlement and no refund to a card; the credit lands on the
account and is consumed by the next invoice.

**Policy change to first-month proration.** A cancelled date now stays in the
first-month proration DENOMINATOR (`total_eligible_classes`) while being
excluded from the numerator, under the new `CANCELLED_AFTER_PRICING_STATUS` in
`contexts/billing/domain/proration.py`. Without this, calling a class off made
the month more expensive per class for the next family through the door: four
$120 Thursdays with Sept 3 cancelled would have quoted a Sept 12 enrollment
$120 x 2/3 = $80 instead of $120 x 2/4 = $60. Pinned by
`test_a_cancelled_date_stays_in_the_denominator_but_never_the_numerator`.

- Enrollment domain: `contexts/enrollment/domain/occurrence_cancellation.py`
  holds the guard — an already-cancelled date, a class that has started or
  finished, and a date on a cancelled session are all refused, with
  `OccurrenceAlreadyCancelled` / `OccurrenceNotCancellable` /
  `OccurrenceNotFound` in `domain/errors.py`. `SessionOccurrence` gains
  `cancelled_at` / `cancelled_by`; `EnrollmentLifecycleEventType` gains
  `occurrence_cancelled`.
- `contexts/enrollment/application/use_cases/cancel_session_occurrence.py`
  CASes the row `scheduled -> cancelled` with `is_billable=False` and
  `is_payable=False` (`MongoSessionOccurrenceRepository.cancel_scheduled`), then
  — best effort, past the commit point — drops the date's one-time make-up/trial
  roster rows (`MongoOccurrenceRosterRepository.remove_for_occurrence`),
  re-opens the make-up requests that targeted it
  (`MongoMakeupRequestRepository.reopen_for_target_occurrence`, now with a
  FRESH `expires_at` so the next expiry sweep cannot swallow an entitlement the
  academy already granted) AND the trial requests assigned to it
  (`MongoTrialRequestRepository.reopen_for_assigned_occurrence`), records a
  lifecycle event per enrolled student, hands the date to billing, and notifies
  the families and staff. A mail or ledger outage never un-cancels a class.
  Make-up and trial students hold a one-time seat and no enrollment on the
  session, so their ids are passed to the notifier explicitly — previously they
  lost the seat in silence. `trials_reopened` is new on the API response.
- Billing:
  `contexts/billing/application/use_cases/apply_occurrence_cancellation.py`
  writes the `session_occurrence_overrides` document that
  `MongoPaymentRepository._occurrences_for_session` has always read and nothing
  ever wrote, then issues one `CLASS_CANCELLATION_CREDIT` per already-invoiced
  family worth `period charge / the classes that charge actually bought`.
  The charge is the invoice's `tuition` + `discount` LINES, not
  `subtotal - discount_cents` — an equipment charge or registration fee added
  to the same monthly invoice would otherwise inflate the credit (and once a
  line is added, `recompute_totals` makes the header subtract the discount
  twice). The divisor is the enrollment's own CONSUMED billing snapshot
  (`billable_remaining_classes` for a prorated month, `total_eligible_classes`
  for a full one), so a late-generated first month is not under-credited by the
  proration ratio; and a date the charge never covered is skipped rather than
  credited. Session pricing goes through the generator's own
  `session_amount_cents` (promoted from `_session_amount_cents` in
  `mongo_monthly_billing.py`) — a bare `amount_cents` read priced a legacy
  session doc at zero and credited nobody while the month was billed in full
  (#609). Skipped, with a recorded reason: a void period invoice, a paused
  family with no invoice, a family whose first month is this period and is not
  priced yet, and `date_not_billed`. Idempotent on
  `source_type="occurrence_cancellation"` +
  `source_id="<occurrence>:<enrollment>"`.
  `MongoPaymentRepository.occurrences_for_period` is new and public so the
  credit divisor can never drift from what the generator prices.
  Reads and the override write live in
  `contexts/billing/infrastructure/mongo_occurrence_cancellation.py`.
- Payroll needed no change — `ComputePayout` already requires
  `status == "completed"` and `is_payable` — but
  `v2/tests/application/test_payout_excludes_cancelled_occurrence.py` now pins
  both guards independently so neither can be dropped silently.
- Route: `POST /api/v2/admin/session-occurrences/{occurrence_id}/cancel`
  (`interfaces/admin/sessions_routes.py`), wired from the new
  `composition/occurrence_cancellation.py` because `composition/admin.py` sits
  at its hard 4800-line structural cap. No coach route: cancelling a class is
  an admin decision.
- Notifications: `RosterAlertAdapter.occurrence_cancelled` in
  `composition/roster_notifications.py`. Families get a TRANSACTIONAL email
  naming the date in the session's own zone, with the zone printed; staff get
  the usual unsubscribable NOTIFICATION copy. The email only promises a credit
  to families billing actually credited — the sync runs after the occurrence
  write and can fail wholesale or skip an individual family — and the staff copy
  carries an explicit warning when it did not run, so an admin never learns
  about a missing credit from a parent. The admin can uncheck "Email the
  families and the coach" for a date already announced by other means.
- Frontend (admin): the "Replacement coaches" card on `/admin/sessions/[id]` is
  folded into a single "Class dates" card (lane 02) that lists every date once
  with its replacement column, a status chip and a "Cancel this date" action —
  two cards over the same component listed every replaced date twice with two
  identical buttons. "Cancel this date" is offered only on a `scheduled` date
  that has not started, matching `assert_occurrence_cancellable`; a past or
  completed date reads "Past" / "Completed" instead of "Scheduled".
  `cancelSessionOccurrence` in `frontend/lib/api/admin.ts`. No new route.
- Frontend (parent): `GetChildSchedule` returns cancelled occurrences (its
  `list_for_session_between` has no status filter, unlike every coach read), so
  the parent calendar (`lib/parent/schedule-events.ts`) now greys them and
  prefixes the title with "Cancelled", the children page strikes the row through
  and hides "Report absence", and the absence-notice picker on
  `/parent/requests` no longer offers a class that will not run.

## Deploy notes

- **Migration 0168 (`0168_occurrence_cancellation.py`) must run before the
  feature is used.** It creates the UNIQUE partial index
  `credit_source_unique` on `account_credit_ledger (academy_id, source_type,
  source_id)` — the real backstop against two admins double-crediting the same
  family for the same date — plus `override_occurrence_unique` on
  `session_occurrence_overrides`, and re-applies the `session_occurrences`
  validator (migration 0133 now declares `cancelled_at` / `cancelled_by`).
  Prod still boots with `V2_RUN_MIGRATIONS_ON_BOOT` false (#629), so run
  `run_pending_migrations` by hand after deploy, as with 0164/0165.
  The credit index's partial filter is pinned to
  `source_type: "occurrence_cancellation"` — the key space this feature
  introduces — and deliberately NOT to "any string `source_type`". OVERPAYMENT
  credits already carry a string `source_type` written through a non-atomic
  check-then-insert in `MongoPaymentRepository.record_manual_payment`, so prod
  may already hold duplicates: a broader filter would abort this migration on
  `DuplicateKeyError`, taking the override index and the validator refresh with
  it, and would turn that pre-existing race into a 500 on a money path. No
  backfill is needed and no existing credit is constrained.
  That overpayment writer is now also wrapped in a `DuplicateKeyError` catch so
  a lost race logs instead of 500ing after the payment doc has committed.
- No new environment variables and no new secrets.
- `session_occurrence_overrides` gets its first ever writer. It is already on
  the tenant-owned allowlist, so no tenancy change is required.
- Existing occurrence documents keep working: `cancelled_at` / `cancelled_by`
  are optional and absent on every row written before this change.

## Risk / rollback

- **Money.** The credit is issued from the invoice's TUITION lines net of the
  tuition discount (or the consumed first-month proration amount, or the monthly
  price net of discount when nothing is priced yet), divided by the classes that
  charge actually bought — including dates cancelled earlier in the same month. An earlier draft shrank that divisor
  after each cancellation and over-refunded a second cancellation (1/4 + 1/3 of
  a four-class month); that is fixed and pinned by
  `test_an_earlier_cancellation_does_not_shrink_the_divisor`. Invoice totals are
  never rewritten — the generator's completeness check compares the tuition line
  to the recomputed gross, and moving it would flag later runs as
  `repair_failed` (#494).
- **Double credit.** Prevented in three places: the use case pre-reads by
  source, `create_if_absent` catches `DuplicateKeyError`, and migration 0168's
  unique index is the backstop. If 0168 has not been applied, two simultaneous
  cancels could each write a credit — apply the migration before announcing the
  feature.
- **Irreversible by design.** There is no un-cancel route in this change. An
  admin who cancels the wrong date must restore it by hand (set the occurrence
  back to `scheduled`, remove the override row, void the credits). A
  `ReinstateSessionOccurrence` use case is the obvious follow-up.
- **Rollback**: revert the PR. The migration's indexes and the override
  documents are harmless if left in place — the generator already knew how to
  read overrides before this change, and un-applying the code simply stops new
  ones being written. Credits already issued stay on the families' accounts,
  which is the correct outcome for a class that genuinely did not run.
- **First-month quotes move.** Any month containing a cancelled date now quotes
  a new mid-month enrollment against the pre-cancellation class count. That is
  the intended fix (it restores the price the family would have paid had the
  cancellation never happened), but it does change quoted first-month amounts
  for those sessions; `schedule_signature` on such a snapshot changes too, since
  the cancelled occurrence is now part of the eligible set.
- A cancelled date still appears on the session's date list and in payroll
  reads; it is excluded by status and `is_payable`, not deleted, so the audit
  trail that the class was scheduled survives.
