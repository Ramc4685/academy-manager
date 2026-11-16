# overnight-followups

PR: TBD

## What changed
A capped autopay ladder's daily recheck (single and family charges) now asks Stripe for a succeeded or processing PaymentIntent on the invoice(s) before charging, and settles that one instead of charging twice once Stripe's 24h idempotency window has passed. Also: the outbox dispatcher's failure log obeys its throttle; coach and parent digest failures reach Sentry once; the `@idempotent` decorator claims its key atomically (a concurrent duplicate gets 409 `request_in_flight` instead of running twice); test-attempt idempotency keys carry the academy and coach; the pathway placement audit row is written by the use case after the placement with a deterministic id; the admin lead follow-up card shows its load error instead of crashing on an empty response.

## Deploy notes
Migration `0240_audit_logs_audit_id_unique` adds a unique partial index on `audit_logs (academy_id, audit_id)` where `audit_id > ""`. It first checks for duplicates and, if any exist, fails naming them (`academy/audit_id xN`); keep the earliest row of each, delete the rest, and re-run. Expect none: every other writer mints a ULID. The Turnstile site key needed no workflow change: `NEXT_PUBLIC_TURNSTILE_SITE_KEY` is already passed to both production frontend build steps (#1185).

## Risk / rollback
The recheck adds one Stripe PaymentIntent search per capped rung per day; if the search fails the rung parks as `stripe_unavailable` rather than charging. Idempotency claims left by a crashed request are taken over after 5 minutes. Roll back by reverting the PR; the 0240 index is harmless to leave in place.
