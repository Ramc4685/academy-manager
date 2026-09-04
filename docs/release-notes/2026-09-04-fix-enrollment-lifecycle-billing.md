# fix-enrollment-lifecycle-billing

PR: #654

## What changed
Closes #651. A family that cancels, withdraws, or pauses could still be
invoiced and auto-charged because the enrollment lifecycle never reached
billing. On prod (2026-09-04) 8 paused enrollments held open invoices and one
paused enrollment still had autopay active.

Policy (owner decision): cancel/withdraw mid-month keeps the current month
payable with no refund; join mid-month stays prorated; a month is skipped when
the enrollment is still paused on its billing day.

- New billing use case `ApplyEnrollmentLifecycle`
  (`contexts/billing/application/use_cases/apply_enrollment_lifecycle.py`)
  voids unpaid future-period invoices (persisting `void_reason` / `voided_at`),
  moves autopay to disabled / paused / active and suppresses dunning ladders.
  Reached through the enrollment port `EnrollmentBillingSync`
  (`composition/lifecycle_billing.py`) from cancel, withdraw, pause, resume,
  session cancel, pause-request approval and parent self-cancel.
- Monthly generator never invoices paused enrollments; pause deferrals now
  cover the paused months instead of the resume month.
- Autopay parents get a pre-charge notice when the invoice is generated and a
  receipt after a successful charge; dues reminders skip autopay-active
  families; the first autopay attempt runs at 09:00 academy-local (was 00:00
  UTC). Voiding an invoice resolves its ladder. Billing day and grace days are
  editable under Settings → Fees.
- Lifecycle consistency outside billing: pause/resume notify family and
  staff; session cancel sweeps paused rows, closes deferrals and cancels
  scheduled resumes; withdraw releases the seat and promotes the waitlist;
  cancel never double-releases a seat; waitlist promotion routes a paused
  student through resume and refuses cancelled sessions; resume refuses a
  cancelled session; make-up approval re-checks enrollment; future make-up
  roster rows are dropped on cancel; waiver reminders and registration
  approval ignore ended enrollments; coaches can open a paused student's
  passport; billing-health hides voided ladders; the parent portal cannot
  re-arm autopay on an ended enrollment, hides the opt-in on a cancelled
  enrollment's last invoice, stops nagging about voided invoices and renders
  void invoices as $0 "Cancelled".

## Deploy notes
No migration, no config. Safe to deploy immediately. Before the next autopay
run (2026-09-08), pause autopay on the paused enrollment that still has it
active and void its September invoice in the admin UI (data fix, owner-owned).

After deploy, confirm: cancelling an enrollment voids its later-month invoices
on `/admin/payments` and the family receives the status email; the dunning
worker log shows attempts starting after 09:00 academy time.

## Risk / rollback
Medium: touches the enrollment write paths and the monthly generator.
Behaviour is fail-open for billing sync (the enrollment write commits and the
lifecycle event records `billing_sync_failed`). Rollback is a revert of this
PR; invoices voided by it stay void and would need re-opening by hand.
