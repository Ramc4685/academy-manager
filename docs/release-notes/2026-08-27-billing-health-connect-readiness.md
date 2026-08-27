# billing-health-connect-readiness

PR: #TBD

## What changed
The admin Billing Health page now leads with a card answering "can parents pay
right now, and where does the money land?" — the Stripe Connect account's
status, charges/payouts enabled, the masked account id, the platform-charge
fallback state, and the stuck-webhook backlog. It reads three ways: green
(charges route to the academy's own account), amber (payments succeed but the
platform fallback is sending money to the platform account), red (no working
account and no fallback, so every parent payment fails).

Backed by a new `GET /api/v2/admin/billing/connect-readiness`.

The quarantined-events stat tile now shows a real count instead of the length
of a list route capped at 50 — "50 quarantined" previously meant anything from
50 to 5,000 — and a Failed Events tile was added beside it, since `failed`
events retrying hourly were invisible on this page entirely.

Not included: the issue also asked for a count of payments taken via the
platform fallback. Nothing persists that today — `transfer_data` exists only
in outbound Stripe request payloads, never in Mongo — so an honest count needs
either a new routing marker stamped at payment-record time (future payments
only) or a live Stripe search on every page load. Both are larger than this
card and are left for a follow-up.

## Deploy notes
None. No migrations, no env vars. The query is covered by the existing
`stripe_event_admin_status` index on `(academy_id, status, received_at)`.

## Risk / rollback
Read-only: one new admin GET route and one card. The webhook counts are
tenant-filtered with an explicit `academy_id` (contract-tested against a
second academy and against unattributed events). If the route fails, the card
renders its own error and the rest of the page is unaffected. Revert the PR to
remove the card and the route.
