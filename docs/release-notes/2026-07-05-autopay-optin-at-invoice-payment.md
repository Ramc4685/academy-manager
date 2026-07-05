# autopay-optin-at-invoice-payment

PR: #285

## What changed
Every one-time invoice or balance payment now offers autopay enrollment at
the same time. Parents see a checkbox — "Enroll in autopay for future
invoices", checked by default — under both Pay buttons on the payments page.
Leaving it checked saves the payment method used and activates autopay for
the covered enrollment(s); unchecking it pays one time only, unchanged from
today. Parents already on autopay never see the checkbox. Activation happens
via both the `checkout.session.completed` webhook and the checkout-status
poll, and never fails the underlying (already-succeeded) payment if
activation itself has a problem — failures are retried via replay instead.

This PR also carries three bug fixes found during its own review cycle
(webhook retryability for failed activations, `checkout_session_id` wiring
into opted-in payment redirects so the poll actually fires, and removal of a
dangling `subscription_id` stamp left on enrollments since PR #266), plus a
docs commit replacing the Codex CLI pre-push review requirement with the
`/code-review` skill.

## Deploy notes
None required. No migration. `enroll_autopay` defaults to `false` so old
API clients are unaffected. Backend + frontend, both covered by the
standard CI deploy pipeline.

## Risk / rollback
Moderate — this changes the default parent payment path (checkbox is
checked by default). If the opt-in causes unwanted autopay enrollments,
revert the merge commit; no irreversible state change beyond the autopay
consent/activation records this PR itself creates, which are already
designed to be safely re-driven by replay.
