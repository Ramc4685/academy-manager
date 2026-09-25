# ACH cash discount: one base, the price after the tuition discount

PR: #TBD

## What changed

- **Same ACH discount on the first attempt and every retry.** Autopay's ACH cash discount is now always a percentage of the price after the tuition discount (sibling, multi-class or manual), as the owner decided on 2026-09-25. Before this change, the first attempt on a monthly-generator invoice used the header's gross `subtotal_cents`, and a retry that found the ACH line already written used the sum of the non-ACH lines, which is net of the `tuition_discount` line. Example: a $100 month with a $20 sibling discount at 2.5% took -$2.50 on the first attempt, and a retry rewrote the line to -$2.00. Both now take -$2.00.
- The base comes from the invoice lines. A header-only `discount_cents` (one with no `tuition_discount` line behind it) is subtracted as well, so it is treated like any other tuition discount. Invoices without a tuition discount get exactly the same ACH discount as before.
- `backend/v2/tests/unit/test_charge_autopay_use_case.py` pins the behavior with a first attempt and a retry on the generator's discounted-month shape, plus a header-only-discount case.

## Deploy notes

- No migration, no new index, no new setting or secret. The change is in `charge_invoice_via_autopay._discount_base_subtotal_cents`.
- Existing ACH discount lines are not corrected in bulk. An open invoice whose line was written at the gross base is rewritten to the net amount on its next autopay attempt, which the charge path already reconciles. Paid invoices are left as charged. The gap per family is `ach_discount_percent` × the tuition discount, so 50¢ on a $20 discount at 2.5%.
- Only academies with `ach_discount_enabled` are affected.

## Risk / rollback

- Low risk. The change only makes the ACH discount smaller, and only for invoices that carry a tuition discount. No family pays more than the tuition-discounted price.
- A separate, unmerged branch (`fix/ledger-discount-double-count`) fixes `recompute_totals` double-subtracting the tuition discount on generator invoices. That fix is independent of this one: the ACH base here reads lines, not the recomputed header.
- Rollback: revert this PR. Lines written by this code are valid ACH discount lines to the old code, which re-bases them on its next attempt.
