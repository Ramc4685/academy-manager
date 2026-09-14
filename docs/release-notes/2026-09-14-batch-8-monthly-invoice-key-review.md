# Let an operator review a monthly invoice key the generator can never repair

PR: #829

## What changed
- Fixes #599 — Invoices recovered before PR #494 keep the old shape and their tuition line is `$setOnInsert`, so the recovery path in `MongoMonthlyBillingRepo` re-derives the same unrepairable failure and re-reports the same handful of `billing_invoice_keys` duplicate-key rows on every monthly generation run, forever.
- Adds a new `reviewed` status on `billing_invoice_keys`, carrying an audit sub-document (`reason`, `reviewed_at`, `reviewed_by`). The duplicate-key branch in the monthly generator now checks for this status and skips straight past a reviewed key instead of re-running recovery against it.
- A reviewed key is automatically un-reviewed (re-flagged for recovery) if the ledger invoice behind it is modified after the review, so a stale review can't silently mask a real regression.
- Skips are counted in a new `skipped_reviewed` total, plumbed through `GenerateMonthlyPaymentsResult`, the scheduler's run totals, and surfaced on the admin `POST /payments/generate-monthly` response so operators can see how many keys were left alone because they were already reviewed.
- The review itself is written only by a new read-only script, `backend/v2/scripts/monthly_invoice_key_repair_review.py` — there is no API endpoint that lets a request mark a key reviewed.

## Deploy notes
- No migrations. `billing_invoice_keys` documents without a `reviewed` status are unaffected; the new status and audit fields are written only when an operator runs the review script against a specific key.
- No new API endpoints; the existing `POST /payments/generate-monthly` response gains one additional field (`skipped_reviewed`).

## Risk / rollback
- Risk: low. The change only affects the narrow duplicate-key recovery branch of monthly generation — it adds a skip path, it does not change how keys are created or how normal (non-duplicate) generation proceeds. New contract and application test coverage (`test_mongo_payment_repo.py`, `test_monthly_invoice_key_repair_review.py`) pins the reviewed-skip and re-flag-on-modification behavior.
- Rollback: revert this PR. No data cleanup is required — `reviewed` keys simply resume going through the normal recovery path on the next generation run.
