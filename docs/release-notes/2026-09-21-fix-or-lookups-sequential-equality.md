# fix-or-lookups-sequential-equality

PR: #TBD

## What changed

- Follow-up to #879 (#878). That PR kept three "match either of two fields" lookups as a single `$or` query with `academy_id` repeated inside each branch, which a local MongoDB 7.0 serves from the indexes. Production runs MongoDB 8.0, and a read-only `explain()` there after migration 0189 showed its planner still scans the academy's documents for that shape (156 of 156 ledger payments examined), while a plain equality lookup on the same fields examines one.
- `get_by_stripe_pi` (Stripe webhook), the admin invoice lookup by id or number, and the billing-health ledger payment lookup now run one equality lookup per field instead of an `$or`. Results are unchanged; each read is served by its index. The admin artifact update now targets the invoice it already resolved by `_id`.

## Deploy notes

Backend-only. No migrations, no env vars. Migration 0189 is already applied in production (registry 107/107, drift audit `ok: true` on 2026-09-21).

## Risk / rollback

Low. Same documents are matched in the same preference order (new field name before the pre-v2 one, `payments` before `ledger_payments`). Verified with read-only `explain()` on production for every equality shape used: 1 key, 1 document, the expected index. To roll back, revert this PR's merge commit.
