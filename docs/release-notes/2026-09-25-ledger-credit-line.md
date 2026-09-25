# Applied account credit survives invoice recomputes

PR: #971

## What changed
- The monthly invoice generator now records account credit it spends on a month's charge as its own "Account credit applied" invoice line (`source_type: account_credit`). Before, the credit lived only in the invoice total, and any later recompute (late fee, admin-added line, ACH autopay discount, line back-fill) billed the family the already-spent credit again.
- `recompute_totals` keeps credit lines out of the subtotal and takes them off the total.
- New owner-run script `backend/scripts/ledger_credit_line_audit.py` lists invoices from before this fix (read-only by default).

## Deploy notes
- No migration. New invoices get the credit line automatically.
- After deploy, the owner runs `MONGO_URL=... DB_NAME=... python backend/scripts/ledger_credit_line_audit.py` (read-only) against prod. `overcharged` rows need an owner decision (refund/credit/restate). `at_risk` rows can be protected with `--apply`, which only inserts the missing credit line and never changes a header.

## Risk / rollback
- Rollback is a code revert. Credit lines already written stay; the old `recompute_totals` would then count them in the subtotal, which still gives the correct total.
- `fix/ledger-discount-double-count` also changes `recompute_totals`; whichever merges second resolves a small textual conflict (the two changes are additive).
