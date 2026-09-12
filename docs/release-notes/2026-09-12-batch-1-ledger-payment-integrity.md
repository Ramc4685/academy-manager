# Ledger payment integrity

PR: #0

## What changed

- Fixes #679 — `ledger_payments` had no DB-level guard on `stripe_payment_intent_id`. Application code deduped on the intent, but a replayed webhook could still record the same money twice and, on an already-settled invoice, land the duplicate as spendable parent credit. Migration 0173 adds a partial unique index on `stripe_payment_intent_id` (partial because manual payments carry no intent) and a read-only audit script (`ledger_payment_intent_duplicate_audit.py`) that lists duplicate groups with their allocations and credits so production can be reconciled before the index is applied. If production already holds duplicates, the migration logs and skips instead of crashing boot.
- Fixes #690 — approved early-withdrawal credits are now unique per enrollment in the store, not just in application code. `RecordWithdrawalDecision` previously decided "already credited?" with a check-then-create, so two concurrent withdrawal approvals for the same enrollment could both pass the pre-read and leave the family two spendable credits. Migration 0174 adds a partial unique index on `account_credit_ledger (academy_id, enrollment_id, type)`, filtered to `type=EARLY_WITHDRAWAL_CREDIT AND status=APPROVED`, so manual/overpayment credits and voided withdrawal credits stay unconstrained and a re-credit after a void is still possible. `RecordWithdrawalDecision` now catches `DuplicateKeyError`, re-reads the winning credit, and returns `credit_already_approved` (shared with the pre-read path via a new `_already_approved` helper) instead of 500ing. A read-only audit script (`withdrawal_credit_duplicate_audit.py`) reports duplicate enrollments and the surplus spendable balance at risk, to run before applying the index by hand in prod.

## Deploy notes

- Two new Mongo migrations: 0173 (`ledger_payments.stripe_payment_intent_id` partial unique index) and 0174 (`account_credit_ledger` partial unique index on approved early-withdrawal credits). Boot migrations are off in prod (#629), so both indexes must be applied by hand.
- Before applying either index in prod, run the paired read-only audit script first (`ledger_payment_intent_duplicate_audit.py` / `withdrawal_credit_duplicate_audit.py`) to check for existing duplicates and reconcile them; the migrations themselves log-and-skip rather than crash if duplicates are already present.
- No new environment variables. Backend-only; frontend untouched.

## Risk / rollback

- Additive integrity guards: normal single-attempt payment and withdrawal-credit flows are unaffected. The webhook and withdrawal-decision code paths now handle the duplicate-key case explicitly instead of relying solely on the pre-read check.
- Rollback: revert this PR. The migrations do not need to be reverted for a code rollback — the indexes are additive and harmless to leave in place; if they must be dropped, do so manually in Mongo.
