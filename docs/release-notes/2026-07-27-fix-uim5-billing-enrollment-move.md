# fix-uim5-billing-enrollment-move

PR: #TBD

## What changed
Admins can now move a student between session types and override a student's
price from the student detail Billing tab, instead of ops running curl. The
move dialog requires a two-step confirm because it prorates the calendar month;
the result shows the credit/charge/net breakdown and the policy version.
Coaches get a read-only proration preview on their session roster so they can
advise parents, with no way to apply the change.

Note on scope: the UIM5 plan described the admin move as possibly issuing a
Stripe invoice. It does not. `MoveStudentSessionType.execute` hardcodes
`stripe_invoice_id = None` and never calls the injected Stripe gateway — it
updates the enrollment and emits a `record_session_type_changed` event carrying
the prorated `net_cents`. The UI copy describes that behavior instead, and the
Stripe invoice row only renders if the backend ever starts returning an id.
Whether the move *should* invoice is a backend question left open.

## Deploy notes
None. Frontend only — the admin and coach billing-enrollment routes already
exist in the v2 BFF and are unchanged.

## Risk / rollback
The admin move changes what a parent is billed: it records a prorated
adjustment applied on the parent's next invoice. No charge is created
synchronously. The period sent to the backend is the calendar month of the move
date (UTC), matching the coach route's server-side `_default_period`; a mismatch
there would prorate the wrong window. The move has no idempotency key and the
backend has no replay guard, so a retry after a network timeout emits a
duplicate change event — the client guards only by disabling the button while
in flight. Coach billing data is deliberately excluded from the offline
localStorage cache so student pricing is not retained on shared devices.
Rollback is UI-only: revert the PR, or drop the two panels from the student
Billing tab and the coach roster row.
