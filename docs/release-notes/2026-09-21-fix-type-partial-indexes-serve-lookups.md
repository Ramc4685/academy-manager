# fix-type-partial-indexes-serve-lookups

PR: #879

## What changed

- Migration `0189_type_partial_indexes_planner_usable` (#878): 25 partial indexes filtered on `$type: "string"` are rebuilt with a `$gt: ""` filter. The old shape enforced uniqueness, but MongoDB never uses it for an ordinary lookup, so reads such as the Stripe webhook's payment-intent, checkout-session and idempotency-key lookups, the checkout webhook's application lookup, and attendance marking's existing-row check were scanning the whole collection. Nothing changes for users today (the collections are small); the cost would have grown with every payment and attendance mark. Index names, keys and uniqueness are unchanged. Values that are absent, `null` or an empty string stay outside the uniqueness rules.
- Lookups that match one of two fields (`get_by_stripe_pi`, the admin invoice lookup by id or number, the billing-health ledger payment lookup) now repeat `academy_id` inside each `$or` branch. With it only at the top level MongoDB cannot use these partial indexes for the branches and scans the academy's documents instead. The pre-v2 `stripe_payment_intent` field gets a small index on `payments` and `ledger_payments` so that branch is served too.
- A new test fails if any migration adds another `$type`-filtered partial index. The nine that remain are keyed on a bare id and belong to #849, which re-keys them per academy.

## Deploy notes

Backend-only. Migrations do not run on boot in production (#629): after the deploy, apply `0189` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations` (apply `0187` and `0188` first if they are still pending). Each index is swapped without a gap in uniqueness: a temporary `<name>__swap` twin is built, the original dropped and rebuilt under its own name, then the twin dropped; an interrupted run resumes. Afterwards run the drift audit (`--dump` on Fly, `--check` locally) and expect `ok: true` with no `__swap` index left, and confirm with a read-only `explain()` that a lookup by `ledger_idempotency_key` on `ledger_payments` names `academy_ledger_payment_idempotency_unique`. No env vars.

## Risk / rollback

Low. `$gt: ""` selects a subset of what `$type: "string"` selected, so no index build can fail on existing data. Verified against a real MongoDB 7 in a throwaway database with every migration replayed: all 25 lookups examine one document through the named index, the three `$or` lookups use both branch indexes, and a second run is a no-op. The test fake evaluates neither partial filters nor query plans. To roll back, revert this PR's merge commit; indexes already applied are safe to leave in place.
