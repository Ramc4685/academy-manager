# demo-academy-walkthrough

PR: TBD

## What changed
The Demo Academy seed now reuses the academy's Badminton Skill Pathway (bootstrapping it only when absent and refusing to run if more than one is active), places Sam on level 2 and Alex on level 1 with dated skill updates, adds one parent-visible coach note, and saves one class recap with a taught skill and practice credit on the latest completed Saturday class. Progress rows are insert-only and keyed by skill, so reruns never duplicate or overwrite updates made in the app, and skills retired in the app are skipped. Email suppressions are now written before progress, so a progress failure cannot leave demo addresses mailable. Parent Payments offers "Set up autopay" only when the class is priced and the academy takes online payments; otherwise it says "Free class, nothing to pay", "Paid directly to the academy" (no Stripe account, with a pay-the-academy note) or "Autopay not available right now" (a Stripe account that cannot charge yet). It shows the Billing portal only for a parent with a Stripe customer, and labels each invoice with the child and invoice number. Absence notices show the class and session date and time, with the submission time on its own line. Coach Delete Account copy no longer talks about children and automatic payments. Settings → Curriculum skill and level descriptions wrap cleanly on narrow phones.

## Deploy notes
None. No migration, env var or manual step. `GET /parent/enrollments` gains `autopay_offer` per row and `billing_portal_available`; `GET /parent/invoices` gains `invoice_number`; `GET /parent/absences` gains `missed_class`. All are additive, and older cached PWA clients ignore them. The seed script is not run by deploy. Rerunning it still resets the demo's attendance and occurrences (unchanged behaviour), so marks entered in the app are lost on a reseed.

## Risk / rollback
Autopay start, checkout and portal endpoints are unchanged; only what the page offers changes. The offer reuses autopay start's own checks (charge route and next month's fee), so a hidden button matches a request that would have been refused; an unreadable charge route fails open and keeps the button, as before. The portal flag reads the parent's academy customer inside the request tenant. Roll back by reverting the PR.
