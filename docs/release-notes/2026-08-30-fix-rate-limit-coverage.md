# rate-limit-coverage

PR: #570

## What changed
Rate limiting covered only three public write paths plus the Stripe
webhook (`#546`). Two gaps are closed. First, the unauthenticated
`POST /api/v2/magic-link/consume` endpoint is now in
`_PUBLIC_WRITE_PATHS`, so anonymous POSTs can no longer hammer the Mongo
token-hash lookup and the Firebase Admin API without limit (IP-keyed,
20/min as with the other public writes). Second, a new
`StripeSessionRateLimitMiddleware` limits every parent endpoint that
creates a real Stripe Checkout/Portal session — `checkout/start`,
`autopay/start`, `billing/portal`, `invoices/{id}/pay`, and
`invoices/pay-balance` — keyed per authenticated user
(`auth_claims.user_id`) per path at 10/min, so one scripted parent
account can no longer exhaust the platform-wide Stripe API budget and
break checkout for every academy. It is wired innermost (after tenancy
attaches claims); requests without claims pass through and 401 at the
route before any Stripe call. Over-limit requests get the existing
stable 429 envelope with `Retry-After`.

## Deploy notes
No configuration, migrations, or operator action required. Limits are
process-local in-memory, same as the existing limiter (GAPS.md #3): on
more than one Fly machine the effective per-user ceiling multiplies by
the machine count, which still caps volumetric abuse.

## Risk / rollback
10 Stripe-session creations per user per path per minute is far above
any legitimate parent flow, so false 429s are very unlikely; a real
burst simply retries after the `Retry-After` window. Magic-link consume
shares the 20/min public-write default, well above one family clicking
an emailed link. Rollback is a straight revert — the middleware is
additive wiring with no data or schema impact.
