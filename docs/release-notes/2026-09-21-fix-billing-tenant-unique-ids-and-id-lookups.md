# fix-billing-tenant-unique-ids-and-id-lookups

PR: #877

## What changed

- Migration `0187_billing_ids_unique_per_academy` (second batch of #849): `payments.payment_id`, `subscriptions.subscription_id`, `subscriptions.stripe_subscription_id` and `student_billing_enrollments.enrollment_id` are now unique per academy instead of across all academies, matching how the code already reads and writes them. With one academy nothing changes for users; it removes a permanent 500 that a second academy onboarded from copied or imported data would have hit.
- Migration `0188_per_academy_id_indexes_planner_usable` corrects a defect in migrations 0150, 0162 and 0186 (the last shipped earlier today in #874). Their per-academy indexes used a `$type: "string"` partial filter. That enforces uniqueness, but MongoDB never uses such an index for an ordinary lookup by id, so by-id reads on `students`, `sessions`, `enrollments`, `session_occurrences` and `attendance` were scanning the academy's documents instead. Measured on production: 0 ms today at under 100 documents per collection, growing with the academy's data. The six indexes are rebuilt with a `$gt: ""` filter, which MongoDB does use; 0187 uses the same filter from the start.
- Ids that are absent, `null` or an empty string stay outside the uniqueness rule.

## Deploy notes

Backend-only. Migrations do not run on boot in production (#629): after the deploy, apply `0187` and `0188` by hand via `fly ssh console -a courtmastr-academy-api` and `backend.v2.migrations.run_pending_migrations`. `0187` pre-flights its collections and aborts without touching any index on a duplicate `(academy_id, <id>)` pair (production had none on 2026-09-21). Every index is created before the one it replaces is dropped. Afterwards run the drift audit (`--dump` on Fly, `--check` locally) and expect `ok: true`, and confirm with a read-only `explain()` that a by-id lookup now names the new index: the drift audit compares index definitions and cannot see whether the planner uses them. No env vars.

## Risk / rollback

Low. The largest affected collection holds about 100 documents, so builds are near-instant; no query or write path changes, only two code comments. Verified against a real MongoDB 7 for all ten indexes (query plan examines one document, same-academy duplicate rejected, cross-academy reuse allowed), because the test fake evaluates neither partial filters nor query plans. To roll back, revert this PR's merge commit; indexes already applied are safe to leave in place.
