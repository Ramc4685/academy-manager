# invoice-email-pay-link

PR: #1164

## What changed
- Invoice emails: the "Pay invoice" button now opens the academy's own `/parent/payments?pay=<invoice>` page, which starts a fresh Stripe Checkout session on every click (after login if needed). An email that bundles the student's whole open balance links to `?pay=<invoice>&bundle=1` and re-mints that same student-scoped bundle (never the parent's family-wide balance, which could include another child's invoices). It used to embed the raw Checkout URL, and Stripe expires invoice sessions after 24 hours, so a parent who opened the monthly email days later landed on Stripe's "You're all done here" page and could not pay (a BLNO family hit this on their November invoice). Emails already sent still carry the dead Stripe link; the parent can pay from the Payments page.
- Backend: the bundle needs a new optional `bundle_student_balance` field on the parent invoice pay request (default false).
- Pay links: every invoice and balance checkout now gets its own Stripe idempotency key. The fixed per-invoice key made Stripe replay the first session for 24 hours, so a portal Pay click within a day of the email got the email's session back, or failed outright with "payment link unavailable" because its success URL differed. The checkout hold still points at the newest session, so the dunning stand-off is unchanged.

## Deploy notes
None. No migration, env var, or manual step.

## Risk / rollback
This also bumps dnspython from 2.9.0 to 2.9.2, fixing CVE-2026-128089, which was failing the CI dependency audit.
Low. If the app link is wrong, parents land on the Payments page and can still use its Pay button. Unique keys mean a fast double-click can open two Checkout sessions; webhook allocation is idempotent and a second payment on a paid invoice quarantines as it already does. Roll back by reverting the PR.
