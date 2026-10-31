# People CRM: invoice email copies for family contacts with "Gets invoices" on (L1b2), migration 0197

PR: #956

## What changed

- A family contact with **Gets invoices (opted in)** switched on now receives a copy of each invoice email the primary parent receives (admin Send / Re-send and the monthly invoice pass). Opt-in only: the switch is still off by default and only staff turn it on.
- The copy shows the month, student, class, balance, invoice total and invoice number, and says the payment link went to the family's primary email. It **never contains the Stripe pay link**; payment and autopay stay with the primary parent.
- Same academy only (contacts are read tenant-scoped, one equality lookup per family id, the invoice's `parent_id` and the parent's canonical user id). One copy per email address; never a second copy to the primary parent's own address.
- At most one copy per invoice per contact email: each copy is claimed in the new `invoice_contact_email_sends` collection through the shared digest claim, so a Re-send, a retried monthly pass or two concurrent sends never mail a contact twice. A failed copy is retried on the next send of that invoice (bounded attempts); a suppressed or bounced address is not retried. A copy failure never fails the parent's send or changes the invoice's delivery status.
- Copies go only after the parent's email succeeded. Autopay pre-charge notices, dunning notices and receipts are unchanged (parent only); wiring contacts into those is a follow-up.
- The "Gets invoices (opted in)" switch description on the family Details tab now says what it does.
- Test-only: the two-tenant isolation test (#953) now knows the `contact_id` path parameter added by #950, which it was failing on.

## Deploy notes

- Migration **0197_invoice_contact_email_sends** is applied by the production migrate job (dry run, then the Fly release command) per `docs/runbooks/migrations-rollout.md`; expect it in the dry run's pending list after 0196 (and 0192-0195 if they have not shipped yet). It only creates one unique index `(academy_id, recipient_email, digest_date)` on the new, empty `invoice_contact_email_sends` collection. Leads with `academy_id`; no partial filter. No document is modified. Never hand-apply it.
- Until 0197 runs the claim is still safe (the shared claim verifies after insert without the index); run the migration with the deploy anyway.
- No feature flag, no environment variable, no backfill. Needs 0196 (`family_contacts`) deployed, which it is ordered after.

## Risk / rollback

- Only families where staff added a contact AND turned Gets invoices on see any change; with no such contact the invoice email path does one extra indexed read per family id and sends exactly as before.
- Revert the PR to roll back: copies stop, the switch text returns to "saved now". The collection and index can stay in place harmlessly.
