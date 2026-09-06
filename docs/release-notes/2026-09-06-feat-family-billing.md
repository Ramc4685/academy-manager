# feat-family-billing

PR: #TBD

## What changed
New admin **Family billing** page at `/admin/families/[parentId]`: one parent's balance,
autopay state with a family-level ON/OFF switch (card on file, next charge date), last
payment, students and classes, the invoice ledger with allocations and credits, a merged
timeline of what the system did (invoices generated/voided, payments, failed charges,
dunning, admin actions with reasons, enrollment lifecycle, emails), and a "Fix something"
block (void, refund, one-time discount, charge card now) where every action requires a
reason. Fed by one read-only endpoint `GET /admin/families/{parent_id}/billing`. One new
write endpoint `POST /admin/families/{parent_id}/autopay/pause` (admin; reason +
request_id; pauses every active enrollment's autopay; audited as `autopay_paused`).
**Billing Setup** is removed: `/admin/billing-setup` redirects to the new **Families**
list (`/admin/families`, same data, rows open the family page); its Send invite / Enable
autopay actions moved to the family header and Charge now became per-invoice. The
student page's Billing tab now links to the family page (price override and move stay).
Bucket rows on Payments link to the family page. The previously uncalled invoice audit
route backs the "Full audit" drawer.

## Deploy notes
None. No migration, no new env vars, no data change. `billing_audit_log` gains an
optional `parent_id` field on new rows only.

## Risk / rollback
Autopay OFF is the only new write; it goes through the existing guarded status
transition (`active → paused`) and never touches invoices or dunning, so the worst case
is a family that stops being auto-charged until the toggle is turned back on. Owner-only
corrections are enforced by the existing owner-gated routes regardless of what the page
shows. Rollback is reverting the PR; `/admin/billing-setup` bookmarks then work again.
