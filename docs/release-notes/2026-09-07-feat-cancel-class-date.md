# feat-cancel-class-date

PR: #TBD

## What changed

Admins can call off a single class date (rain-out, sick coach, holiday) instead
of cancelling the whole session, and the money and payroll follow automatically.
Issue #671.

**Owner policy implemented here** (state it to the academy before deploying):
a cancelled date automatically credits every enrolled family the date's share of
the month through the account credit ledger when the period is already invoiced.
When the period is not yet invoiced, the generator simply prices the month
without that date — no credit is issued, because the family was never charged
for it. There is no make-up entitlement and no refund to a card; the credit
lands on the account and is consumed by the next invoice.

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
  (`MongoMakeupRequestRepository.reopen_for_target_occurrence`), records a
  lifecycle event per enrolled student, hands the date to billing, and notifies
  the families and staff. A mail or ledger outage never un-cancels a class.
- Billing:
  `contexts/billing/application/use_cases/apply_occurrence_cancellation.py`
  writes the `session_occurrence_overrides` document that
  `MongoPaymentRepository._occurrences_for_session` has always read and nothing
  ever wrote, then issues one `CLASS_CANCELLATION_CREDIT` per already-invoiced
  family worth `period charge / classes the month was priced against`. Skipped,
  with a recorded reason: a void period invoice, a paused family with no
  invoice, and a family whose first month is this period (rule 1 already
  excludes the date from their proration). Idempotent on
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
  the usual unsubscribable NOTIFICATION copy. The admin can uncheck "Email the
  families and the coach" for a date already announced by other means.
- Frontend: a "Class dates" card on `/admin/sessions/[id]` lists every date with
  a Cancelled chip and a "Cancel this date" action; the dialog requires a reason
  (it reaches families verbatim) and states the credit consequence.
  `cancelSessionOccurrence` in `frontend/lib/api/admin.ts`. No new route.

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
  The credit index is partial on `source_type: {$type: "string"}`, so existing
  early-withdrawal and manual credits (which have no `source_type`) are
  untouched and no backfill is needed.
- No new environment variables and no new secrets.
- `session_occurrence_overrides` gets its first ever writer. It is already on
  the tenant-owned allowlist, so no tenancy change is required.
- Existing occurrence documents keep working: `cancelled_at` / `cancelled_by`
  are optional and absent on every row written before this change.

## Risk / rollback

- **Money.** The credit is issued from the invoice's tuition net of discount
  (or the monthly price net of discount when the period is not yet invoiced),
  divided by the classes the month was priced against — including dates
  cancelled earlier in the same month. An earlier draft shrank that divisor
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
- A cancelled date still appears on the session's date list and in payroll
  reads; it is excluded by status and `is_payable`, not deleted, so the audit
  trail that the class was scheduled survives.
