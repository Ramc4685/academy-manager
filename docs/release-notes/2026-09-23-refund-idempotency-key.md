# Refunds are deduped per request, not per amount + reason, and the key is academy-scoped (#930)

PR: #TBD

## What changed

- **Bug.** Both owner refund routes deduped on the refund's shape. `IssueRefund` cached under `refund:{payment_id}:{amount}:{reason}` (no academy), and the invoice refund cached under `invoice_refund:{academy}:{invoice}:{amount}:{reason}`. A second real refund with the same amount and reason inside the 7-day idempotency TTL got the first result back. No Stripe refund was made and the owner still got a 200. Because the `IssueRefund` key had no academy, a refund in academy B of a payment id that academy A had already refunded could also replay A's Stripe refund. B's invoice then counted a refund that was never issued. A real-mongod test showed both before the fix.
- **New policy** (`backend/v2/contexts/billing/application/refund_idempotency.py`, same approach as manual payments in #511):
  - `POST /api/v2/admin/payments/refund` and `POST /api/v2/admin/billing/invoices/{id}/refund` accept an `Idempotency-Key` header (max 200 chars). The client sends one key per refund attempt.
  - Same key again: the first result is replayed and nothing moves.
  - New key with the same amount and reason: this is a new refund. It is issued, or it is rejected with an error (`400 Billing.RefundExceedsAmount`, or 409 "invoice has no refundable allocated payment").
  - Same key used for a different refund: `422 Billing.RefundIdempotencyKeyReused`, and nothing moves.
  - No key, and an identical refund was made inside the TTL: `409 Billing.RefundPossibleDuplicate`. The owner confirms by resending with a key. A keyless repeat is never replayed silently.
  - Every key includes the academy that owns the refunded record. `IssueRefund` now reads the payment through its tenant-scoped repo before checking the cache, so another academy's payment id returns 404 and never gets a cached result.
- **Stripe idempotency key.** `StripeGateway.issue_refund` now takes `idempotency_key`, and the real gateway passes it to `Refund.create`. The key is `{kind}:{academy}:{target}:{sha256(request key)[:32]}`: the same on every retry of one request and different for each new request. If a retry happens after our cache write was lost, Stripe returns the original refund. `FakeStripeGateway` behaves the same way: the same key returns the original refund id, and the same key with different parameters raises an error. It also records every call in `refund_requests`.
- **Internal callers** pass fixed keys for the one refund each of them owns. The capacity auto-refund uses `capacity_failed` and the registration-decline refund uses `registration_declined`, so a redelivered event or a retried decline replays that refund instead of getting a 409.
- **Frontend.** `refundPayment` and `refundAdminInvoice` send an `Idempotency-Key`. The Payments refund dialog, the invoice detail refund and the family Billing tab keep one key per refund attempt, so a retry after an error reuses the key. After a success, or when the amount or reason changes, they use a new key.
- **Audit script.** `backend/scripts/find_deduped_refunds.py` is read-only (`find` / `find_one` only). It reports:
  - invoice refunds whose `refund_issued` audit total for a payment is more than that payment's `refunded_cents`;
  - Stripe refund ids cached for more than one request target;
  - pre-#930 shape-keyed cache entries, with the window in which an identical request would have been silently dropped.
  It exits 1 on either of the first two findings. It has not been run against any real database.
- **Tests.** Added: `backend/v2/tests/contract/test_refund_idempotency_money_path.py` (real mongod: same-key replay, new-key second refund, over-balance rejection, keyless 409, key reuse 422, deterministic Stripe key after a lost cache write, cross-academy on both routes), `test_find_deduped_refunds_audit.py` (synthetic data, read-only proxy), `backend/v2/tests/unit/test_refund_idempotency_keys.py`, and interface tests for the header in `test_admin_billing.py`. Updated: the invoice-refund retry test in `test_admin_billing_idempotency.py` now uses a key.

## Deploy notes

- No migration. The existing `idempotency_keys` collection, its unique `key` index and its 7-day TTL are reused.
- Refund cache entries written before this deploy under `refund:{payment}:{amount}:{reason}` are no longer read. They expire through the TTL. Pre-#930 invoice entries share the new keyless key format, so a keyless identical repeat within their TTL gets the new 409 and is not replayed.
- Deploy the backend before (or with) the frontend. An older frontend sends no key and still works, but a second identical refund from it now gets a 409 instead of being silently dropped.
- Before deciding whether any family is owed money, the owner can run the audit script against a read-only copy.

## Risk / rollback

- Medium: this changes the dedupe on an owner-only money path.
  - A client that retries without a key now gets a 409 instead of a replay. That is safe (nothing moves), but it is visible.
  - A request that was in flight across the deploy boundary does not see its old cache entry. There was no Stripe idempotency key before this change, so this is no worse than before.
- Concurrent requests with different keys on the `/payments/refund` path are still guarded only by the balance check, as before. The invoice path keeps its optimistic claim on the invoice.
- Rollback: revert the PR. New cache entries (`payment_refund:*`, keyed `invoice_refund:*:key:*`) are ignored by the old code and expire through the TTL. There is no schema to undo.
