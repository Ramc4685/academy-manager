# fix-admin-reports-payment-feed-guard

PR: #667

## What changed
The admin **Reports** page (`/admin/reports`) no longer crashes into its error boundary
when a query resolves with a payload that is missing one of its collections. It read
`paymentFeedQuery.data?.payments.length` — the `?.` guarded only `data`, so a response
without a `payments` key threw `TypeError: undefined is not an object`. Every list the
page renders now comes from a guarded local with a default (`recentPayments`,
`dashboardEmptyStates`, `agingBuckets`, `expenseCategories`, `projectedSessions`), which
is the pattern `/admin` already used for the same feed. `projected.by_session` had the
same shape and would have thrown next, once the payment feed stopped throwing first.

Each nested group of the reports dashboard (`attendance`, `sessions`, `profit_and_loss`,
`expenses`, `payroll`, `collections_risk`) is guarded on its own rather than on the
response being truthy, so a partial payload renders "No data" per tile instead of
throwing. The four top-level money scalars are guarded on the field, so a missing one
cannot render `$NaN`.

Two places now say "unknown" where they used to imply health:

- A payment feed that resolves without a `payments` array renders **"Could not load
  recent payments."** rather than "No payments received yet." — an unreadable ledger is
  not an empty one. A genuine `[]` still reads as empty.
- The payment-readiness card on **Billing health** renders **"Unavailable"** for missing
  webhook counts rather than "0 quarantined · 0 failed", which would have hidden
  unrecovered Stripe failures and could contradict the quarantine tile beside it (fed by
  a separate query). `connected_account` keeps a zeroed fallback: every field on it fails
  toward the alarming reading, so an incomplete response over-warns rather than conceals.

No visible change when the API returns a complete payload: both pages render exactly as
before.

## Deploy notes
None. Frontend only — no migration, no new env vars, no API or data change.

## Risk / rollback
The change only affects reads; no data is written, and no query, endpoint, or rendered
value changes when the payload is complete. On a partial payload the affected section now
degrades on its own instead of taking the page down. Where that degraded state would
otherwise assert a fact about money we could not read, it reports the failure instead —
so a malformed backend response surfaces as "Could not load recent payments." or
"Unavailable" rather than being silently absorbed as a zero. Rollback is reverting the
PR; the reports page then returns to crashing into the error boundary on a partial feed.
