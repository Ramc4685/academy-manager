# Billing follow-ups from the Lane A5 money-path tests (#928, #929, #930, #931, #932)

PR: #952

## What changed

- **#928: card charges are owner-only.** `POST /admin/billing/invoices/{id}/charge-autopay` and `POST /admin/billing/setup/{parent_id}/charge` now use `require_owner()` and are listed in `OWNER_ONLY_ROUTE_PATHS`. A non-owner admin gets the same 404 as every other owner-only route. The shared use case `charge_invoice_as_admin` requires `actor_roles` and raises `ChargeRequiresOwner` before it touches idempotency, the cache, the audit log or Stripe, so leaving out the roles fails closed. `charge_card` is added to `OWNER_ONLY_ACTIONS`, and the Family "Fix something" panel hides "Charge card now" from non-owners. This follows the 2026-09-22 staff-tier decision.
- **#931: one allocation per idempotency key under concurrent callers.** The `payment_allocations` claim row now has a state. It is inserted `pending` and only its owner marks it `committed`, after the guarded debit and invoice post land. A same-key caller waits for the claim and replays it (up to 10 s) instead of repairing around the winner and rolling it back. If its first lookup missed, it re-checks the key before failing. A claim abandoned by a crashed process is healed after a 60 s lease. Rollback is conditional on the row still being `pending`, and it re-derives both the invoice and the payment. Rows written before this change have no state and count as committed.
- **#930: refunds are deduped per request, and the key is academy-scoped.** Both refund routes accept an `Idempotency-Key` header, and the frontend sends one per refund attempt:
  - Same key again: the first result is replayed.
  - New key: a new refund is issued, or rejected with an error (`RefundExceedsAmount`, or 409 when nothing is refundable).
  - Same key with different parameters: 422 `RefundIdempotencyKeyReused`.
  - No key while an identical refund was made inside the TTL: 409 `RefundPossibleDuplicate`.

  Every key carries the owning academy. Stripe `Refund.create` now gets a deterministic idempotency key per request.
- **#929: the Billing tab shows refunds.** The family billing read model projects the invoice's `refunded_cents`, a per-payment refund total and the amount of each refund in the timeline. It adds `net_paid_cents` and family totals (`paid`, `refunded`, `net`). The Refund action is not offered once card money is fully refunded, and the dialog's ceiling excludes earlier refunds. No new tier logic; #553 is not built.
- **#932: parent portal invoices match every alias.** The new billing use cases `ListParentInvoices` and `GetParentInvoice` resolve the parent's ids through identity's `resolve_parent_aliases` (one equality lookup per field, never `$or`). They then read invoices with one `academy_id` + `parent_id` equality query per alias. The home balance, Pay balance and Pay invoice use the same set, so what the portal shows as due is what it lets the parent pay. Authorization is unchanged in kind: every read is tenant-scoped, and an invoice is visible only if its `parent_id` is one of the parent's own ids.
- **Read-only audit scripts, not run against any real database:**
  - `backend/scripts/payment_allocation_claim_audit.py` (#931): lists duplicate allocations per key, paid invoices with no allocation row, and stale pending claims.
  - `backend/scripts/find_deduped_refunds.py` (#930): lists refunds recorded on an invoice beyond the payment's `refunded_cents`, Stripe refund ids cached for more than one target, and old shape-keyed cache entries.
- **Tests.** New real-mongod contract tests: `test_card_charge_owner_gate.py`, `test_allocate_payment_concurrent_claim.py`, `test_refund_idempotency_money_path.py`, `test_parent_invoice_alias_access.py`, plus new cases in `test_family_billing_money_path.py`. Also new: interface and unit tests, audit-script tests, vitest (`FixSomethingPanel.test.ts`, `family-view.test.ts`), and the updated `admin-family-billing.spec.ts` non-owner case. The strict xfails in `test_money_route_staff_tiers.py` and the refunded-amount xfail are now passing tests.

## Deploy notes

- No new migration. #931 reuses the 0091 unique index, and the new fields are allowed by the 0132 validator. #932's alias lookups use the 0193 users indexes that are already waiting for the next deploy, along with 0192 and 0194.
- No config or env changes. Deploy the backend before or together with the frontend. An older frontend sends no refund key, so a second identical refund from it gets a 409 instead of being silently dropped.
- Non-owner admins lose "Charge card now" on deploy. Tell academy staff.
- Optional, owner's call: run the two read-only audit scripts against a read-only copy to learn whether a swallowed refund (#930) or a duplicate or orphaned allocation (#931) ever happened in prod. They change nothing, and any finding is repaired by hand.

## Risk / rollback

- **#928:** a behaviour change for admins without `owner`, as the owner decided. Admins migrated before 0165 also hold `owner`.
- **#930:**
  - A client that retries without a key now gets a 409 instead of a replay. Nothing moves.
  - Concurrent refunds with different keys on `/payments/refund` are still guarded only by the balance check, as before.
- **#931:**
  - A same-key caller may wait up to 10 s and then get a retryable error.
  - A crashed claim heals after 60 s instead of immediately.
- **#929:** read-only. A payment's refund total is the largest of its stored records. The write side can drift when legacy and ledger payment rows share an id; that is a separate follow-up.
- **#932:** parents may now see, and pay, invoices that were always theirs but were hidden.
- **Rollback:** revert the PR. There is no schema change. Old code ignores the `allocation_state`/`claimed_at` fields and the new cache keys, which expire through the TTL.
