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
same shape and would have thrown next, once the payment feed stopped throwing first. The
payment-readiness card on **Billing health** got the same treatment for
`connected_account` and `webhook_events`.

No visible change when the API returns a complete payload: the page renders exactly as
before. When a collection is missing, the section shows its existing empty state instead
of taking the whole page down.

## Deploy notes
None. Frontend only — no migration, no new env vars, no API or data change.

## Risk / rollback
The change only adds defaults on reads; no data is written and no query, endpoint, or
rendered value changes when the payload is complete. The one behaviour change is that a
partial payload now degrades to an empty section rather than an error boundary, which
can mask a backend response that is genuinely malformed — the underlying request still
shows up in the network tab and in Sentry. Rollback is reverting the PR; the page
returns to crashing into the error boundary on a partial feed.
