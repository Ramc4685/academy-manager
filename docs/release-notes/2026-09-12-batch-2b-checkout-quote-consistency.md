# Batch 2b: checkout quote consistency

PR: #0

## What changed

- Fixes #731 — Parent checkout now charges the exact quote the Review & pay step displayed instead of re-quoting at click time. `POST /parent/checkout/start` accepts an optional `snapshot_id` (the snapshot the review step rendered); the composition consumes that snapshot — scoped to the parent and session, so one family cannot consume another's quote — and prices Stripe from it. When the snapshot is expired, already consumed, or belongs to someone else, checkout raises `QuoteExpired` instead of silently substituting a fresh quote, and the wizard re-prices and keeps the parent on the review step. Previously the displayed snapshot was never consumed and stayed `OPEN` forever while checkout silently re-quoted, so a class crossing the two-hour cutoff (or a cancelled/repriced date) could charge a figure the parent never saw.
- Follow-up hardening on the same fix: `POST /parent/enrollments/quote` no longer accepts a client-supplied `start_date`. That date fed directly into `billing_start_at`, and a date late in the month drops every class before it as `BEFORE_BILLING_START`, producing a near-zero `OPEN` snapshot that checkout would then consume and charge while the enrollment proceeded at full value. The parent quote path now always prices from the server clock (the same instant checkout falls back to), so a review-step quote can never come in under what the server would charge on its own. An older client bundle that still posts the field is ignored rather than rejected. Admins keep a start date on their own trusted quote endpoint, which is not client-facing.

## Deploy notes

None. No migrations, no schema changes, no new environment variables. Both changes are backend request/response contract changes plus a corresponding frontend update to pass (or stop passing) fields; existing OPEN snapshots created before this change remain valid and are simply consumed the first time they're referenced instead of orphaned.

## Risk / rollback

Low risk: the changes narrow existing behavior (consume the shown snapshot instead of re-quoting; stop trusting a client-supplied start date) rather than introducing new code paths, and are covered by new unit and interface tests (`test_parent_composition.py`, `test_parent_sessions_checkout.py`). Rollback is a revert of this PR; no data backfill is required since no persisted documents change shape.
