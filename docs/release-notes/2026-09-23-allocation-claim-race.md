# Billing: one allocation per idempotency key, even when two callers race on it (#931)

PR: #TBD

## What changed

- **The race.** In `MongoBillingLedgerRepository.allocate_payment`, the insert of the `payment_allocations` row (unique on `academy_id` + `idempotency_key`, migration 0091) already decided the winner. The loser, though, went straight to the repair path. That path rebuilt the invoice and the payment from every allocation row it could see, the winner's half-written row included, and saved them with a plain overwrite. The winner's guarded debit or invoice update then failed, and its rollback deleted its own allocation row. Result: an invoice marked paid with no allocation behind it, the payment's funds spendable again, and a later retry with the same key would allocate a second time. #926's record-payment claim keeps normal double submits away from this path. It could still happen when two retries take over one abandoned claim, or when webhook retries arrive together.
- **The fix (billing infrastructure only).** The allocation row is now a claim with a state. It is inserted as `allocation_state: "pending"` with `claimed_at`. Only the caller that inserted it sets it to `"committed"`, and only after its guarded debit and invoice post have both landed. A second caller with the same key that finds a pending row now waits for it (polling for up to 10 s) and then returns the same allocation. It no longer repairs the invoice or payment while the row is pending. If the owner rolled back, the waiting caller claims the key again from scratch. If a claim is still pending after its 60 s lease (the owner process died), the next caller heals it from the allocation rows, as before, and commits it with a conditional update.
- **Rollback is conditional and complete.** `_rollback_pending_allocation` deletes the row only while it is still `pending`. If a takeover already committed the row, the allocation stands and is returned. After a real rollback it now re-derives the invoice as well as the payment, so an invoice another repair already posted cannot be left paid with no allocation.
- Rows written before this change have no `allocation_state` and are treated as committed. No change to `admin.py`, routes, staff tiers or the frontend.
- **Audit script (read-only).** `backend/scripts/payment_allocation_claim_audit.py` only runs `find`: no writes, no repairs, no index builds. It lists, per academy: more than one allocation row under one idempotency key; invoices marked `paid`/`partially_paid` that have no allocation row at all (the #931 end state; invoices settled outside the ledger can also show up here, so each one needs review); and pending claims older than the lease. It has not been run against any real database.
- **Tests.** New real-mongod contract tests in `backend/v2/tests/contract/test_allocate_payment_concurrent_claim.py`:
  - `asyncio.gather` two callers with the same key, 15 rounds. Each round must give one row, the same allocation id to both callers, the invoice posted once and the payment debited once.
  - The exact #931 interleaving, forced to happen: a full-payment case and a partial-payment case. Both failed before the fix, with the winner rolled back.
  - A lease-expired abandoned claim is healed.

  `test_payment_allocation_claim_audit.py` checks that the audit finds each of its three states and makes no writes.

## Deploy notes

- No migration. No new index: claims use the existing 0091 unique index `academy_allocation_idempotency_unique`. The new `allocation_state` and `claimed_at` fields are allowed by the 0132 validator, which does not forbid extra properties.
- No backfill: rows without `allocation_state` count as committed.
- Optional, owner's call: run the read-only audit (`MONGO_URL=... DB_NAME=... python backend/scripts/payment_allocation_claim_audit.py`) to see whether the race ever happened. It changes nothing. Any row it lists is fixed by hand.

## Risk / rollback

- Medium-low: this is a money path, but only the same-key collision path changes behaviour. A second caller now waits up to 10 s for a claim in flight instead of repairing around it. If the claim is still in flight after that, it gets `ValueError(... retry)`, which callers already handle for the existing CAS misses.
- A claim abandoned by a crashed process is healed only once its 60 s lease has passed. Before, it was healed immediately, but that immediate heal was exactly what raced a live owner.
- Rollback: revert the PR. Rows written as `pending`/`committed` stay readable by the old code, which ignores the extra fields. A row left `pending` by a crash is healed by the old code's repair path, as before.
