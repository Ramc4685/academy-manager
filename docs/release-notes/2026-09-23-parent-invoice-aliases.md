# Parent portal invoices: match every id the parent answers to, not only the exact login id (#932)

PR: #TBD

## What changed

- **Bug.** `GET /api/v2/parent/invoices` and `GET /api/v2/parent/invoices/{invoice_id}` compared the invoice's stored `parent_id` to the signed-in parent's id exactly. A parent whose invoices were stamped with another of their own ids (for example their Firebase uid instead of the roster `user_id`) saw an empty list and got a 404 on the detail page. It failed closed; no one saw another family's data.
- **Fix.** Two new billing use cases, `ListParentInvoices` and `GetParentInvoice` (`backend/v2/contexts/billing/application/use_cases/parent_invoices.py`). They resolve the parent's aliases through identity's `resolve_parent_aliases`: one equality lookup per identity field, never an `$or` across fields (#878/#894), the same lookup People CRM A3 uses. Then they read invoices through the tenant-scoped ledger. The new ledger method `MongoBillingLedgerRepository.list_invoices_for_parent_aliases` runs one `academy_id` + `parent_id` equality query per alias, on the existing `(academy_id, parent_id, created_at)` index. It merges the results by `invoice_id`, returns newest first and keeps the 100-invoice limit. Ports: `ParentIdentityAliases` and `ParentInvoiceLedger` in `billing/application/ports.py`. `composition/parent.py` now only wires the two use cases. `admin.py` is untouched.
- **Authorization is unchanged in kind.** Aliases widen only the identity side. Every invoice read keeps `academy_id`, and a detail read is allowed only when the invoice's `parent_id` is one of the parent's own ids. Tenant membership is not enough (#664). A parent id with no `users` row falls back to exact matching, which is the old behaviour.
- **The parent home balance** reads through the same list use case, so it now counts invoices stored under an alias too.
- **The pay paths use the same set.** `start_balance_payment_for_parent` builds its payable set from `ListParentInvoices`. `start_invoice_payment_for_parent` keeps the tenant-scoped `get_invoice` fetch and then checks ownership with the new `parent_owns_invoice` helper (billing context), which accepts any of the parent's own ids. The banner, the invoice list, Pay balance and Pay invoice now always agree, so the portal never shows a Pay button for money it cannot take. The balance idempotency key is unchanged: the requesting `parent_id` plus the sorted invoice ids.
- **Tests.** New real-mongod contract test `backend/v2/tests/contract/test_parent_invoice_alias_access.py` covers:
  - an invoice stored under the Firebase uid, both directions of aliasing, and the exact match;
  - a parent id with no users row, and an unknown parent (empty list or 404);
  - another family's invoice in the same tenant, under either of its ids, stays invisible;
  - the same parent's invoice in another tenant stays invisible;
  - merged results stay newest-first and respect the limit;
  - Pay balance charges the sum of invoices under the user id and the Firebase uid, and records both invoice ids;
  - Pay balance succeeds when the family's only open invoice is under an alias, and Pay invoice accepts an alias-stamped invoice in both directions;
  - another family's invoice in the same tenant, and the same parent's invoice in another tenant, stay unpayable.

## Deploy notes

- No migration. The per-alias reads use the existing `invoices` `(academy_id, parent_id, created_at)` index (0112/0132). The users alias lookup uses the 0193 indexes, which are already pending deploy with Lane A.
- No configuration or environment changes.

## Risk / rollback

- Low. This changes which invoices two parent GET endpoints, the parent home balance and the two parent pay endpoints treat as the parent's own. A parent may now see invoices that were previously hidden from them. Those invoices were always theirs.
- Pay balance may now charge more than before, because the checkout covers invoices that were previously skipped. The amount always matches what the banner shows.
- Rollback: revert the PR. There is no migration or schema change to undo.
